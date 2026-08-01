import os
import discord
from discord.ext import commands
from discord import app_commands


TOKEN = os.getenv("TOKEN")


intents = discord.Intents.default()
intents.members = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, reconnect=True)

    async def setup_hook(self):
        await self.tree.sync()
        print("✅ 슬래시 명령어 동기화 완료")

    async def on_ready(self):
        print(f"✅ 로그인 완료: {self.user}")

    # 봇 연결이 끊겼을 때
    async def on_disconnect(self):
        print("⚠️ 디스코드 서버와의 연결이 끊겼습니다. 재연결을 시도합니다...")

    # 연결이 복구되었을 때
    async def on_resumed(self):
        print("🔄 디스코드 서버와 다시 연결되었습니다!")

bot = MyBot()

@bot.tree.command(
    name="유저정보",
    description="유저의 정보를 확인합니다."
)
@app_commands.describe(
    유저="정보를 확인할 유저"
)
async def 유저정보(
    interaction: discord.Interaction,
    유저: discord.Member = None
):
    await interaction.response.defer()

    if 유저 is None:
        유저 = interaction.user

    embed = discord.Embed(
        title="👤 유저 정보",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=유저.display_avatar.url)
    embed.add_field(name="📛 닉네임", value=유저.display_name, inline=False)
    embed.add_field(name="🆔 사용자 ID", value=str(유저.id), inline=False)
    embed.add_field(name="🤖 봇 여부", value="예" if 유저.bot else "아니오", inline=False)
    
    if 유저.joined_at:
        embed.add_field(name="📅 서버 가입일", value=유저.joined_at.strftime("%Y-%m-%d %H:%M"), inline=False)

    embed.set_footer(text=f"요청자: {interaction.user.display_name}")

    await interaction.followup.send(embed=embed)

bot.run(TOKEN)
