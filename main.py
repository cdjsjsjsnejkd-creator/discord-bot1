import discord
from discord.ext import commands
from discord import app_commands
import random  # 3개 중 1개 무작위 선택을 위해 추가
import os      # Render 환경변수(TOKEN)를 가져오기 위해 추가

# Render 환경변수에서 토큰 가져오기
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

    async def on_disconnect(self):
        print("⚠️ 디스코드 서버와의 연결이 끊겼습니다. 재연결을 시도합니다...")

    async def on_resumed(self):
        print("🔄 디스코드 서버와 다시 연결되었습니다!")

bot = MyBot()


# --------------------------------------------------
# [기능 1] 투표용 버튼 뷰(View) 클래스
# --------------------------------------------------
class PollView(discord.ui.View):
    def __init__(self, topic, option1, option2):
        super().__init__(timeout=None) # 투표 버튼이 꺼지지 않도록 무제한 설정
        self.topic = topic
        self.option1 = option1
        self.option2 = option2
        self.votes = {} # 유저 중복 투표 방지용 { user_id: 1 또는 2 }

        # 1번 선택지 버튼
        self.btn1 = discord.ui.Button(label=f"1. {option1} (0표)", style=discord.ButtonStyle.primary, custom_id="poll_opt1")
        self.btn1.callback = self.on_btn1_click
        self.add_item(self.btn1)

        # 2번 선택지 버튼
        self.btn2 = discord.ui.Button(label=f"2. {option2} (0표)", style=discord.ButtonStyle.success, custom_id="poll_opt2")
        self.btn2.callback = self.on_btn2_click
        self.add_item(self.btn2)

    async def update_poll(self, interaction: discord.Interaction):
        count1 = list(self.votes.values()).count(1)
        count2 = list(self.votes.values()).count(2)

        self.btn1.label = f"1. {self.option1} ({count1}표)"
        self.btn2.label = f"2. {self.option2} ({count2}표)"

        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name=f"1️⃣ {self.option1}", value=f"**{count1}표**", inline=True)
        embed.set_field_at(1, name=f"2️⃣ {self.option2}", value=f"**{count2}표**", inline=True)

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_btn1_click(self, interaction: discord.Interaction):
        self.votes[interaction.user.id] = 1
        await self.update_poll(interaction)

    async def on_btn2_click(self, interaction: discord.Interaction):
        self.votes[interaction.user.id] = 2
        await self.update_poll(interaction)


# --------------------------------------------------
# [명령어 1] /유저정보
# --------------------------------------------------
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


# --------------------------------------------------
# [명령어 2] /투표
# --------------------------------------------------
@bot.tree.command(
    name="투표",
    description="간단한 투표를 진행합니다."
)
@app_commands.describe(
    주제="투표 주제를 입력하세요",
    항목1="첫 번째 선택지",
    항목2="두 번째 선택지"
)
async def 투표(
    interaction: discord.Interaction,
    주제: str,
    항목1: str,
    항목2: str
):
    embed = discord.Embed(
        title=f"📊 투표: {주제}",
        description="아래 버튼을 눌러 투표에 참여하세요!",
        color=discord.Color.gold()
    )
    embed.add_field(name=f"1️⃣ {항목1}", value="**0표**", inline=True)
    embed.add_field(name=f"2️⃣ {항목2}", value="**0표**", inline=True)
    embed.set_footer(text=f"투표 발의자: {interaction.user.display_name}")

    view = PollView(주제, 항목1, 항목2)
    await interaction.response.send_message(embed=embed, view=view)


# --------------------------------------------------
# [명령어 3] /골라줘
# --------------------------------------------------
@bot.tree.command(
    name="골라줘",
    description="3개의 항목 중 1개를 랜덤으로 골라줍니다."
)
@app_commands.describe(
    항목1="첫 번째 선택지",
    항목2="두 번째 선택지",
    항목3="세 번째 선택지"
)
async def 골라줘(
    interaction: discord.Interaction,
    항목1: str,
    항목2: str,
    항목3: str
):
    # 3초 초과 방지를 위한 응답 대기
    await interaction.response.defer()

    options = [항목1, 항목2, 항목3]
    selected = random.choice(options) # 3개 중 무작위 1개 추출

    embed = discord.Embed(
        title="🎲 고르기 결과!",
        description="고민하지 마세요! 봇의 선택은 바로...",
        color=discord.Color.green()
    )
    embed.add_field(name="📋 후보 목록", value=f"1. {항목1}\n2. {항목2}\n3. {항목3}", inline=False)
    embed.add_field(name="✨ 당첨!", value=f"👉 **{selected}**", inline=False)
    embed.set_footer(text=f"요청자: {interaction.user.display_name}")

    await interaction.followup.send(embed=embed)


# 봇 실행
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ 에러: TOKEN 환경변수가 설정되지 않았습니다.")

