import discord
from discord.ext import commands
from discord import app_commands
import random
import os
import sqlite3
import time
import re
import urllib.request
import json
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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # AI 이미지 검열용 (선택)

# --------------------------------------------------
# [DB 설정] SQLite 데이터베이스 연결 및 테이블 생성
# --------------------------------------------------
conn = sqlite3.connect('points.db')
cursor = conn.cursor()

# 포인트 테이블
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        points INTEGER DEFAULT 0,
        last_chat REAL DEFAULT 0
    )
''')

# 자동 검열 설정 테이블 (서버별 설정 저장)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id INTEGER PRIMARY KEY,
        auto_mod INTEGER DEFAULT 0
    )
''')
conn.commit()

# --------------------------------------------------
# [Intents 설정]
# --------------------------------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # 채팅 및 첨부파일 감지 필수

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, reconnect=True)

    async def setup_hook(self):
        await self.tree.sync()
        print("✅ 슬래시 명령어 동기화 완료")

    async def on_ready(self):
        print(f"✅ 로그인 완료: {self.user}")

bot = MyBot()

# --------------------------------------------------
# [검열 로직] 위험 링크 & AI 이미지 검수 함수
# --------------------------------------------------
SUSPICIOUS_KEYWORDS = [
    "free-nitro", "discord-gift", "steamcommunity-gifts", 
    "grabify", "iplogger", "bit.ly", "tinyurl.com"
]

def check_suspicious_url(text: str) -> bool:
    """위험 키워드 및 패턴을 기반으로 링크를 차단합니다."""
    urls = re.findall(r'https?://[^\s]+', text)
    if not urls:
        return False

    for url in urls:
        for kw in SUSPICIOUS_KEYWORDS:
            if kw in url.lower():
                return True
    return False

async def analyze_image_with_ai(image_url: str) -> bool:
    """OpenAI Vision API를 활용하여 이미지가 위험한지 분석합니다."""
    if not OPENAI_API_KEY:
        return False  # API 키가 없으면 기본 통과

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Is this image spam, phishing, scam, pornographic, or dangerous? Answer ONLY 'YES' or 'NO'."},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }
            ],
            "max_tokens": 10
        }
        
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", 
                                     data=json.dumps(data).encode('utf-8'), 
                                     headers=headers)
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            answer = res_data['choices'][0]['message']['content'].strip().upper()
            return "YES" in answer
    except Exception as e:
        print(f"⚠️ AI 이미지 검수 오류: {e}")
        return False

# --------------------------------------------------
# [이벤트] 채팅 감지, 포인트 및 자동 검열 처리
# --------------------------------------------------
CHAT_COOLDOWN = 60

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # 1. 자동 검열 기능 확인
    cursor.execute('SELECT auto_mod FROM guild_settings WHERE guild_id = ?', (message.guild.id,))
    mod_setting = cursor.fetchone()
    is_automod_enabled = mod_setting[0] if mod_setting else 0

    if is_automod_enabled:
        # A. 텍스트/링크 검열
        if check_suspicious_url(message.content):
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention}님, 의심스러운 링크/스팸은 전송할 수 없습니다!", delete_after=5)
            return

        # B. 이미지 검열
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    is_dangerous = await analyze_image_with_ai(attachment.url)
                    if is_dangerous:
                        await message.delete()
                        await message.channel.send(f"🚨 {message.author.mention}님, AI 검열에 의해 부적절하거나 유해한 이미지가 삭제되었습니다.", delete_after=5)
                        return

    # 2. 포인트 지급 로직
    user_id = message.author.id
    current_time = time.time()

    cursor.execute('SELECT points, last_chat FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if result is None:
        earned = random.randint(5, 15)
        cursor.execute('INSERT INTO users (user_id, points, last_chat) VALUES (?, ?, ?)',
                       (user_id, earned, current_time))
        conn.commit()
    else:
        points, last_chat = result
        if current_time - last_chat >= CHAT_COOLDOWN:
            earned = random.randint(5, 15)
            cursor.execute('UPDATE users SET points = points + ?, last_chat = ? WHERE user_id = ?',
                           (earned, current_time, user_id))
            conn.commit()

    await bot.process_commands(message)

# --------------------------------------------------
# [명령어] /자동검열 설정 (관리자 전용)
# --------------------------------------------------
@bot.tree.command(name="자동검열", description="스팸, 의심스러운 링크 및 유해 이미지를 자동으로 삭제하는 기능을 설정합니다.")
@app_commands.describe(상태="자동 검열 기능을 켜거나 끕니다.")
@app_commands.choices(상태=[
    app_commands.Choice(name="활성화 (ON)", value="on"),
    app_commands.Choice(name="비활성화 (OFF)", value="off")
])
@app_commands.checks.has_permissions(administrator=True)
async def auto_mod_command(interaction: discord.Interaction, 상태: app_commands.Choice[str]):
    guild_id = interaction.guild_id
    enabled = 1 if 상태.value == "on" else 0

    cursor.execute('''
        INSERT INTO guild_settings (guild_id, auto_mod) VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET auto_mod = ?
    ''', (guild_id, enabled, enabled))
    conn.commit()

    status_str = "활성화(ON) 🟢" if enabled else "비활성화(OFF) 🔴"
    embed = discord.Embed(
        title="🛡️ 자동 검열 설정 변경",
        description=f"스팸 링크 및 유해 이미지 검열 상태가 **{status_str}** 로 변경되었습니다.",
        color=discord.Color.green() if enabled else discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)

# --------------------------------------------------
# [기존 명령어 모음]
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

@bot.tree.command(name="투표", description="간단한 투표를 진행합니다.")
@app_commands.describe(주제="투표 주제를 입력하세요", 항목1="첫 번째 선택지", 항목2="두 번째 선택지")
async def 투표(interaction: discord.Interaction, 주제: str, 항목1: str, 항목2: str):
    embed = discord.Embed(title=f"📊 투표: {주제}", description="아래 버튼을 눌러 투표에 참여하세요!", color=discord.Color.gold())
    embed.add_field(name=f"1️⃣ {항목1}", value="**0표**", inline=True)
    embed.add_field(name=f"2️⃣ {항목2}", value="**0표**", inline=True)
    embed.set_footer(text=f"투표 발의자: {interaction.user.display_name}")

    view = PollView(주제, 항목1, 항목2)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="골라줘", description="3개의 항목 중 1개를 랜덤으로 골라줍니다.")
@app_commands.describe(항목1="첫 번째 선택지", 항목2="두 번째 선택지", 항목3="세 번째 선택지")
async def 골라줘(interaction: discord.Interaction, 항목1: str, 항목2: str, 항목3: str):
    await interaction.response.defer()
    options = [항목1, 항목2, 항목3]
    selected = random.choice(options)

    embed = discord.Embed(title="🎲 고르기 결과!", description="고민하지 마세요! 봇의 선택은 바로...", color=discord.Color.green())
    embed.add_field(name="📋 후보 목록", value=f"1. {항목1}\n2. {항목2}\n3. {항목3}", inline=False)
    embed.add_field(name="✨ 당첨!", value=f"👉 **{selected}**", inline=False)
    embed.set_footer(text=f"요청자: {interaction.user.display_name}")

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="공지", description="공지사항을 작성합니다.")
@app_commands.describe(제목="공지 제목", 내용="공지 내용")
@app_commands.checks.has_permissions(administrator=True)
async def notice(interaction: discord.Interaction, 제목: str, 내용: str):
    embed = discord.Embed(title=f"📢 {제목}", description=내용, color=discord.Color.blue())
    embed.set_footer(text=f"작성자 : {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    embed.timestamp = discord.utils.utcnow()
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="업데이트", description="업데이트 공지를 작성합니다.")
@app_commands.describe(제목="업데이트 제목", 내용="업데이트 내용")
@app_commands.checks.has_permissions(administrator=True)
async def update(interaction: discord.Interaction, 제목: str, 내용: str):
    embed = discord.Embed(title=f"🛠️ {제목}", description=내용, color=discord.Color.green())
    embed.set_footer(text=f"작성자 : {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    embed.timestamp = discord.utils.utcnow()
    await interaction.response.send_message(embed=embed)

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
# [실행]
# --------------------------------------------------
if TOKEN:
    keep_alive()
    bot.run(TOKEN)
else:
    print("❌ 에러: TOKEN 환경변수가 설정되지 않았습니다.")



