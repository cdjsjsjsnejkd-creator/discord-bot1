import discord
from discord.ext import commands
from discord import app_commands

TOKEN = "여기에_봇_토큰"

intents = discord.Intents.default()

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("슬래시 명령어 동기화 완료!")

bot = MyBot()

@bot.event
async def on_ready():
    print(f"로그인 성공 : {bot.user}")

# -------------------------------
# /공지
# -------------------------------
@bot.tree.command(name="공지", description="공지사항을 작성합니다.")
@app_commands.describe(
    제목="공지 제목",
    내용="공지 내용"
)
@app_commands.checks.has_permissions(administrator=True)
async def notice(interaction: discord.Interaction, 제목: str, 내용: str):

    embed = discord.Embed(
        title=f"📢 {제목}",
        description=내용,
        color=discord.Color.blue()
    )

    embed.set_footer(
        text=f"작성자 : {interaction.user.display_name}",
        icon_url=interaction.user.display_avatar.url
    )

    embed.timestamp = discord.utils.utcnow()

    await interaction.response.send_message(embed=embed)

# -------------------------------
# /업데이트
# -------------------------------
@bot.tree.command(name="업데이트", description="업데이트 공지를 작성합니다.")
@app_commands.describe(
    제목="업데이트 제목",
    내용="업데이트 내용"
)
@app_commands.checks.has_permissions(administrator=True)
async def update(interaction: discord.Interaction, 제목: str, 내용: str):

    embed = discord.Embed(
        title=f"🛠️ {제목}",
        description=내용,
        color=discord.Color.green()
    )

    embed.set_footer(
        text=f"작성자 : {interaction.user.display_name}",
        icon_url=interaction.user.display_avatar.url
    )

    embed.timestamp = discord.utils.utcnow()

    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)