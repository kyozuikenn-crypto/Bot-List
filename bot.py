import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime
import pytz
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
#  KONFIGURASI
# ============================================================
TOKEN    = os.environ.get("TOKEN", "TOKEN_BOT_MU_DI_SINI")
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Jakarta")

# ============================================================
#  WEB SERVER KECIL — supaya Railway/hosting tidak matikan bot
# ============================================================
class KeepAlive(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    def log_message(self, format, *args):
        pass  # sembunyikan log request

def run_web():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), KeepAlive)
    server.serve_forever()

# Jalankan web server di thread terpisah
threading.Thread(target=run_web, daemon=True).start()

# ============================================================
#  SETUP BOT
# ============================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

DATA_FILE   = "list_data.json"
CONFIG_FILE = "server_config.json"

# ============================================================
#  HELPER: Data list
# ============================================================
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(config: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def get_server_config(guild_id: int) -> dict:
    config = load_config()
    return config.get(str(guild_id), {})

def set_server_config(guild_id: int, data: dict):
    config = load_config()
    config[str(guild_id)] = data
    save_config(config)

def get_sesi_aktif(data: dict, guild_id: int):
    for sesi_id, sesi in data.items():
        if sesi.get("status") == "open" and sesi.get("guild_id") == guild_id:
            return sesi_id, sesi
    return None, None

def is_admin(member: discord.Member, guild: discord.Guild) -> bool:
    """Cek apakah member adalah owner server atau punya role admin yang diset."""
    if member.id == guild.owner_id:
        return True
    cfg = get_server_config(guild.id)
    role_id = cfg.get("role_id")
    if role_id:
        return any(r.id == int(role_id) for r in member.roles)
    return False

def embed_list(sesi: dict, tutup: bool = False) -> discord.Embed:
    nama_list = sesi.get("nama_list", "List")
    jam_close = sesi.get("jam_close", "-")
    peserta   = sesi.get("peserta", {})
    tz_name   = TIMEZONE.split("/")[-1]

    if tutup:
        warna = discord.Color.red()
        status_teks = "🔒 List ditutup"
    else:
        warna = discord.Color.green()
        status_teks = f"🟢 List terbuka • Tutup jam **{jam_close} {tz_name}**"

    embed = discord.Embed(
        title=f"📋 {nama_list}",
        description=status_teks,
        color=warna,
        timestamp=datetime.utcnow()
    )

    if peserta:
        baris = []
        for i, (uid, info) in enumerate(peserta.items(), 1):
            baris.append(f"`{i}.` <@{uid}> — {info['waktu']}")
        embed.add_field(name=f"Peserta ({len(peserta)})", value="\n".join(baris), inline=False)
    else:
        embed.add_field(name="Peserta", value="_Belum ada yang list_", inline=False)

    embed.set_footer(text="1 orang hanya bisa list 1 kali")
    return embed

# ============================================================
#  VIEW: Tombol Klik List
# ============================================================
class TombolList(discord.ui.View):
    def __init__(self, sesi_id: str):
        super().__init__(timeout=None)
        self.sesi_id = sesi_id

    @discord.ui.button(label="✅ Klik List", style=discord.ButtonStyle.success, custom_id="klik_list")
    async def klik_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            data     = load_data()
            guild_id = interaction.guild_id
            sesi_id, sesi = get_sesi_aktif(data, guild_id)

            if not sesi_id:
                await interaction.followup.send("❌ Tidak ada list yang sedang dibuka.", ephemeral=True)
                return

            tz       = pytz.timezone(TIMEZONE)
            sekarang = datetime.now(tz)
            jam, menit = map(int, sesi.get("jam_close", "23:59").split(":"))
            close_dt = sekarang.replace(hour=jam, minute=menit, second=0, microsecond=0)

            if sekarang >= close_dt:
                await interaction.followup.send("🔒 List sudah ditutup. Waktu habis!", ephemeral=True)
                return

            uid     = str(interaction.user.id)
            peserta = sesi.setdefault("peserta", {})

            if uid in peserta:
                await interaction.followup.send(
                    f"⚠️ Kamu sudah list pada **{peserta[uid]['waktu']}**. Tidak bisa list lagi!",
                    ephemeral=True
                )
                return

            waktu_sekarang       = sekarang.strftime("%H:%M")
            peserta[uid]         = {"nama": interaction.user.display_name, "waktu": waktu_sekarang}
            save_data(data)

            embed = embed_list(sesi)
            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send(
                f"✅ **{interaction.user.display_name}** berhasil list pada **{waktu_sekarang}**!",
                ephemeral=True
            )
        except Exception as e:
            print(f"Error klik_list: {e}")
            await interaction.followup.send("❌ Terjadi error, coba lagi.", ephemeral=True)

# ============================================================
#  VIEW: Panel Admin
# ============================================================
class PanelAdmin(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📋 Buka List Baru", style=discord.ButtonStyle.primary, custom_id="buka_list")
    async def buka_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user, interaction.guild):
            await interaction.response.send_message("❌ Hanya admin server yang bisa membuka list.", ephemeral=True)
            return

        data = load_data()
        sesi_id, _ = get_sesi_aktif(data, interaction.guild_id)
        if sesi_id:
            await interaction.response.send_message("⚠️ Sudah ada list yang sedang berjalan!", ephemeral=True)
            return

        await interaction.response.send_modal(ModalBukaList())

# ============================================================
#  MODAL: Input nama list dan jam close
# ============================================================
class ModalBukaList(discord.ui.Modal, title="Buka List Baru"):
    nama = discord.ui.TextInput(
        label="Nama List",
        placeholder="Contoh: Daftar Hadir, Slot Turnamen, dll.",
        required=True,
        max_length=100
    )
    jam_close = discord.ui.TextInput(
        label="Jam Tutup (HH:MM, contoh 20:00)",
        placeholder="20:00",
        required=True,
        max_length=5
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            jam, menit = map(int, self.jam_close.value.strip().split(":"))
            assert 0 <= jam <= 23 and 0 <= menit <= 59
        except Exception:
            await interaction.followup.send("❌ Format jam salah. Gunakan HH:MM (contoh: 20:00)", ephemeral=True)
            return

        guild_id = interaction.guild_id
        cfg      = get_server_config(guild_id)
        channel_id = cfg.get("channel_id")

        if not channel_id:
            await interaction.followup.send(
                "⚠️ Channel belum diatur! Gunakan `/setup` dulu untuk pilih channel.", ephemeral=True
            )
            return

        channel = bot.get_channel(int(channel_id))
        if not channel:
            await interaction.followup.send("❌ Channel tidak ditemukan. Coba `/setup` ulang.", ephemeral=True)
            return

        data    = load_data()
        sesi_id = str(int(datetime.utcnow().timestamp()))
        data[sesi_id] = {
            "status"    : "open",
            "guild_id"  : guild_id,
            "nama_list" : self.nama.value,
            "jam_close" : self.jam_close.value.strip(),
            "pembuka"   : str(interaction.user.id),
            "peserta"   : {}
        }
        save_data(data)

        embed = embed_list(data[sesi_id])
        view  = TombolList(sesi_id)
        msg   = await channel.send(embed=embed, view=view)

        data[sesi_id]["message_id"] = msg.id
        data[sesi_id]["channel_id"] = channel_id
        save_data(data)

        await interaction.followup.send(
            f"✅ List **{self.nama.value}** dibuka!\nTutup otomatis jam **{self.jam_close.value.strip()}**.",
            ephemeral=True
        )

# ============================================================
#  TASK: Cek jam close setiap menit
# ============================================================
@tasks.loop(minutes=1)
async def cek_jam_close():
    try:
        data     = load_data()
        tz       = pytz.timezone(TIMEZONE)
        sekarang = datetime.now(tz)

        for sesi_id, sesi in list(data.items()):
            if sesi.get("status") != "open":
                continue
            jam, menit = map(int, sesi.get("jam_close", "23:59").split(":"))
            close_dt   = sekarang.replace(hour=jam, minute=menit, second=0, microsecond=0)

            if sekarang >= close_dt:
                data[sesi_id]["status"] = "closed"
                save_data(data)

                channel_id = sesi.get("channel_id")
                message_id = sesi.get("message_id")
                if channel_id and message_id:
                    channel = bot.get_channel(int(channel_id))
                    if channel:
                        try:
                            msg   = await channel.fetch_message(int(message_id))
                            embed = embed_list(sesi, tutup=True)
                            view  = discord.ui.View()
                            btn   = discord.ui.Button(
                                label="🔒 List Ditutup",
                                style=discord.ButtonStyle.danger,
                                disabled=True
                            )
                            view.add_item(btn)
                            await msg.edit(embed=embed, view=view)
                            await channel.send("🔒 **List telah ditutup otomatis!**")
                        except Exception as e:
                            print(f"Error tutup otomatis: {e}")
    except Exception as e:
        print(f"Error cek_jam_close: {e}")

# ============================================================
#  SLASH COMMAND: Setup — pilih channel saja
#  Role otomatis: owner server + siapa saja yang di-assign admin
# ============================================================
@tree.command(name="setup", description="Pilih channel untuk list (hanya owner server)")
@app_commands.describe(channel="Channel tempat list akan dikirim")
async def setup(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    try:
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("❌ Hanya **owner server** yang bisa menggunakan `/setup`.", ephemeral=True)
            return

        cfg = get_server_config(interaction.guild_id)
        cfg["channel_id"] = channel.id
        set_server_config(interaction.guild_id, cfg)

        await interaction.followup.send(
            f"✅ **Setup berhasil!**\n"
            f"📢 Channel list: {channel.mention}\n"
            f"👑 Yang bisa buka list: **owner server** + role yang di-assign via `/setadmin`",
            ephemeral=True
        )
    except Exception as e:
        print(f"Error setup: {e}")
        await interaction.followup.send("❌ Terjadi error saat setup.", ephemeral=True)

# ============================================================
#  SLASH COMMAND: Set Admin Role tambahan
# ============================================================
@tree.command(name="setadmin", description="Tambah role yang bisa buka list (hanya owner server)")
@app_commands.describe(role="Role yang bisa membuka dan menutup list")
async def setadmin(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(ephemeral=True)
    try:
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("❌ Hanya **owner server** yang bisa menggunakan `/setadmin`.", ephemeral=True)
            return

        cfg = get_server_config(interaction.guild_id)
        cfg["role_id"]   = role.id
        cfg["role_name"] = role.name
        set_server_config(interaction.guild_id, cfg)

        await interaction.followup.send(
            f"✅ Role **{role.name}** sekarang bisa membuka list!",
            ephemeral=True
        )
    except Exception as e:
        print(f"Error setadmin: {e}")
        await interaction.followup.send("❌ Terjadi error.", ephemeral=True)

# ============================================================
#  SLASH COMMAND: Panel Admin
# ============================================================
@tree.command(name="panel", description="Buka panel untuk membuka list")
async def panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        if not is_admin(interaction.user, interaction.guild):
            await interaction.followup.send("❌ Kamu tidak punya akses.", ephemeral=True)
            return

        cfg = get_server_config(interaction.guild_id)
        if not cfg.get("channel_id"):
            await interaction.followup.send(
                "⚠️ Channel belum diatur! Owner server harus ketik `/setup` dulu.", ephemeral=True
            )
            return

        view  = PanelAdmin()
        embed = discord.Embed(
            title="🎛️ Panel Admin",
            description="Klik tombol di bawah untuk membuka list baru.",
            color=discord.Color.blurple()
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        print(f"Error panel: {e}")
        await interaction.followup.send("❌ Terjadi error.", ephemeral=True)

# ============================================================
#  SLASH COMMAND: Tutup list manual
# ============================================================
@tree.command(name="tutup", description="Tutup list yang sedang berjalan")
async def tutup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        if not is_admin(interaction.user, interaction.guild):
            await interaction.followup.send("❌ Kamu tidak punya akses.", ephemeral=True)
            return

        data = load_data()
        sesi_id, sesi = get_sesi_aktif(data, interaction.guild_id)
        if not sesi_id:
            await interaction.followup.send("⚠️ Tidak ada list yang sedang berjalan.", ephemeral=True)
            return

        data[sesi_id]["status"] = "closed"
        save_data(data)

        channel_id = sesi.get("channel_id")
        message_id = sesi.get("message_id")
        if channel_id and message_id:
            channel = bot.get_channel(int(channel_id))
            if channel:
                try:
                    msg   = await channel.fetch_message(int(message_id))
                    embed = embed_list(sesi, tutup=True)
                    view  = discord.ui.View()
                    btn   = discord.ui.Button(label="🔒 List Ditutup", style=discord.ButtonStyle.danger, disabled=True)
                    view.add_item(btn)
                    await msg.edit(embed=embed, view=view)
                    await channel.send("🔒 **List ditutup secara manual oleh admin.**")
                except Exception as e:
                    print(f"Error tutup: {e}")

        await interaction.followup.send("✅ List berhasil ditutup.", ephemeral=True)
    except Exception as e:
        print(f"Error tutup command: {e}")
        await interaction.followup.send("❌ Terjadi error.", ephemeral=True)

# ============================================================
#  SLASH COMMAND: Lihat peserta
# ============================================================
@tree.command(name="lihat", description="Lihat daftar peserta list saat ini")
async def lihat(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        data = load_data()
        sesi_id, sesi = get_sesi_aktif(data, interaction.guild_id)
        if not sesi_id:
            await interaction.followup.send("⚠️ Tidak ada list yang sedang berjalan.", ephemeral=True)
            return
        embed = embed_list(sesi)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Error lihat: {e}")
        await interaction.followup.send("❌ Terjadi error.", ephemeral=True)

# ============================================================
#  SLASH COMMAND: Cek setup server
# ============================================================
@tree.command(name="ceksetup", description="Cek konfigurasi bot di server ini")
async def ceksetup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg        = get_server_config(interaction.guild_id)
        channel_id = cfg.get("channel_id")
        role_name  = cfg.get("role_name", "Belum diatur")
        channel_teks = f"<#{channel_id}>" if channel_id else "Belum diatur"

        embed = discord.Embed(title="⚙️ Konfigurasi Server", color=discord.Color.blurple())
        embed.add_field(name="📢 Channel List", value=channel_teks, inline=False)
        embed.add_field(name="👑 Role Admin Tambahan", value=role_name, inline=False)
        embed.add_field(name="🔑 Owner Server", value=f"<@{interaction.guild.owner_id}>", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Error ceksetup: {e}")
        await interaction.followup.send("❌ Terjadi error.", ephemeral=True)

# ============================================================
#  ON READY
# ============================================================
@bot.event
async def on_ready():
    await tree.sync()
    if not cek_jam_close.is_running():
        cek_jam_close.start()
    print(f"✅ Bot aktif: {bot.user}")
    print(f"   Slash commands synced.")
    print(f"   Aktif di {len(bot.guilds)} server.")

# ============================================================
#  JALANKAN
# ============================================================
bot.run(TOKEN, reconnect=True)
