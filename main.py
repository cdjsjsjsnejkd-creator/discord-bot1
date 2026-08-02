import discord
from discord.ext import commands
from discord import app_commands
import random
import os
import sqlite3
import time
from flask import Flask
from threading import Thread

# --------------------------------------------------
# [Render 24시간 유지용 셀프 웹 서버]
# --------------------------------------------------
app = Flask('')

@app.route('/')
def home():
    return "Bot is Alive!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# Render 환경변수에서 토큰 가져오기
TOKEN = os.getenv("TOKEN")

# --------------------------------------------------
# [DB 설정] SQLite 데이터베이스 연결 및 테이블 생성
# --------------------------------------------------
conn = sqlite3.connect('points.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        points INTEGER DEFAULT 0,
        last_chat REAL DEFAULT 0
    )
''')
conn.commit()

# --------------------------------------------------
# [Intents 설정] 채팅 감지를 위해 message_content 필수
# --------------------------------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # 채팅 감지 권한 추가

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
# [이벤트] 채팅 감지 및 포인트 지급 (60초 쿨타임)
# --------------------------------------------------
CHAT_COOLDOWN = 60  # 포인트 지급 쿨타임 (초)

@bot.event
async def on_message(message: discord.Message):
    # 봇 메시지이거나 DM 메시지인 경우 무시
    if message.author.bot or not message.guild:
        return

    user_id = message.author.id
    current_time = time.time()

    cursor.execute('SELECT points, last_chat FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if result is None:
        # 신규 유저 등록 및 첫 포인트 지급 (5~15pt)
        earned = random.randint(5, 15)
        cursor.execute('INSERT INTO users (user_id, points, last_chat) VALUES (?, ?, ?)',
                       (user_id, earned, current_time))
        conn.commit()
    else:
        points, last_chat = result
        # 쿨타임이 지났으면 포인트 추가 지급
        if current_time - last_chat >= CHAT_COOLDOWN:
            earned = random.randint(5, 15)
            cursor.execute('UPDATE users SET points = points + ?, last_chat = ? WHERE user_id = ?',
                           (earned, current_time, user_id))
            conn.commit()

    await bot.process_commands(message)


# --------------------------------------------------
# [기능 1] 투표용 버튼 뷰(View) 클래스
# --------------------------------------------------
class PollView(discord.ui.View):
    def __init__(self, topic, option1, option2):
        super().__init__(timeout=None)
        self.topic = topic
        self.option1 = option1
        self.option2 = option2
        self.votes = {}

        self.btn1 = discord.ui.Button(label=f"1. {option1} (0표)", style=discord.ButtonStyle.primary, custom_id="poll_opt1")
        self.btn1.callback = self.on_btn1_click
        self.add_item(self.btn1)

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
@bot.tree.command(name="유저정보", description="유저의 정보를 확인합니다.")
@app_commands.describe(유저="정보를 확인할 유저")
async def 유저정보(interaction: discord.Interaction, 유저: discord.Member = None):
    await interaction.response.defer()

    if 유저 is None:
        유저 = interaction.user

    embed = discord.Embed(title="👤 유저 정보", color=discord.Color.blue())
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
@bot.tree.command(name="투표", description="간단한 투표를 진행합니다.")
@app_commands.describe(주제="투표 주제를 입력하세요", 항목1="첫 번째 선택지", 항목2="두 번째 선택지")
async def 투표(interaction: discord.Interaction, 주제: str, 항목1: str, 항목2: str):
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
@bot.tree.command(name="골라줘", description="3개의 항목 중 1개를 랜덤으로 골라줍니다.")
@app_commands.describe(항목1="첫 번째 선택지", 항목2="두 번째 선택지", 항목3="세 번째 선택지")
async def 골라줘(interaction: discord.Interaction, 항목1: str, 항목2: str, 항목3: str):
    await interaction.response.defer()

    options = [항목1, 항목2, 항목3]
    selected = random.choice(options)

    embed = discord.Embed(
        title="🎲 고르기 결과!",
        description="고민하지 마세요! 봇의 선택은 바로...",
        color=discord.Color.green()
    )
    embed.add_field(name="📋 후보 목록", value=f"1. {항목1}\n2. {항목2}\n3. {항목3}", inline=False)
    embed.add_field(name="✨ 당첨!", value=f"👉 **{selected}**", inline=False)
    embed.set_footer(text=f"요청자: {interaction.user.display_name}")

    await interaction.followup.send(embed=embed)


# --------------------------------------------------
# [명령어 4] /공지 (관리자 전용)
# --------------------------------------------------
@bot.tree.command(name="공지", description="공지사항을 작성합니다.")
@app_commands.describe(제목="공지 제목", 내용="공지 내용")
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


# --------------------------------------------------
# [명령어 5] /업데이트 (관리자 전용)
# --------------------------------------------------
@bot.tree.command(name="업데이트", description="업데이트 공지를 작성합니다.")
@app_commands.describe(제목="업데이트 제목", 내용="업데이트 내용")
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


# --------------------------------------------------
# [명령어 6] /포인트 (나 또는 타인 조회)
# --------------------------------------------------
@bot.tree.command(name="포인트", description="나 또는 다른 유저의 포인트를 확인합니다.")
@app_commands.describe(유저="포인트를 조회할 유저 (선택)")
async def check_points(interaction: discord.Interaction, 유저: discord.User = None):
    target = 유저 or interaction.user

    cursor.execute('SELECT points FROM users WHERE user_id = ?', (target.id,))
    result = cursor.fetchone()
    pts = result[0] if result else 0

    embed = discord.Embed(title="🪙 포인트 정보", color=discord.Color.gold())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="유저", value=target.mention, inline=True)
    embed.add_field(name="보유 포인트", value=f"**{pts:,}** PT", inline=True)
    embed.set_footer(text=f"요청자: {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)


# --------------------------------------------------
# [명령어 7] /랭킹 (Top 10)
# --------------------------------------------------
@bot.tree.command(name="랭킹", description="포인트 순위 Top 10을 확인합니다.")
async def show_leaderboard(interaction: discord.Interaction):
    cursor.execute('SELECT user_id, points FROM users ORDER BY points DESC LIMIT 10')
    rows = cursor.fetchall()

    if not rows:
        await interaction.response.send_message("아직 등록된 포인트 데이터가 없습니다.")
        return

    embed = discord.Embed(title="🏆 포인트 랭킹 Top 10", color=discord.Color.gold())
    
    rank_text = ""
    for idx, (user_id, pts) in enumerate(rows, start=1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"`{idx}.`"
        rank_text += f"{medal} <@{user_id}> - **{pts:,}** PT\n"

    embed.description = rank_text
    embed.set_footer(text=f"요청자: {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)


# --------------------------------------------------
# [실행] 웹 서버와 봇을 동시에 실행
# --------------------------------------------------
if TOKEN:
    keep_alive()  # 24시간 유지용 셀프 웹 서버 실행
    bot.run(TOKEN)
else:
    print("❌ 에러: TOKEN 환경변수가 설정되지 않았습니다.")


