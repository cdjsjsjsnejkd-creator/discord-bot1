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

cursor.execute('''
    CREATE TABLE IF NOT EXISTS warnings (
        user_id INTEGER PRIMARY KEY,
        warnings INTEGER DEFAULT 0
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS tictactoe_stats (
        user_id INTEGER PRIMARY KEY,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        draws INTEGER DEFAULT 0
    )
''')
conn.commit()

# --------------------------------------------------
# [Intents 설정]
# --------------------------------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

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
# [이벤트] 채팅 감지 및 포인트 지급 (60초 쿨타임)
# --------------------------------------------------
CHAT_COOLDOWN = 60

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

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
# [신규 기능] 틱택토 게임 로직 및 View
# --------------------------------------------------

class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        assert self.view is not None
        view: TicTacToeView = self.view

        if interaction.user != view.player:
            await interaction.response.send_message("❌ 당신의 게임이 아닙니다!", ephemeral=True)
            return

        if view.board[self.y][self.x] != 0:
            await interaction.response.send_message("❌ 이미 선택된 칸입니다!", ephemeral=True)
            return

        # 유저 턴 (❌ 표시)
        view.board[self.y][self.x] = 1
        self.style = discord.ButtonStyle.danger
        self.label = "❌"
        self.disabled = True

        # 라운드 승패 판정 (유저 승리 체크)
        if view.check_winner(1):
            view.p_wins += 1
            await view.next_round(interaction, f"🎉 **{view.current_round}라운드 승리!**")
            return

        # 무승부 체크
        if view.is_board_full():
            await view.next_round(interaction, f"🤝 **{view.current_round}라운드 무승부!**")
            return

        # AI 턴 (⭕ 표시)
        view.bot_move()

        # AI 승리 체크
        if view.check_winner(2):
            view.b_wins += 1
            await view.next_round(interaction, f"🤖 **{view.current_round}라운드 AI 승리!**")
            return

        if view.is_board_full():
            await view.next_round(interaction, f"🤝 **{view.current_round}라운드 무승부!**")
            return

        await interaction.response.edit_message(embed=view.make_embed(), view=view)


class TicTacToeView(discord.ui.View):
    def __init__(self, player: discord.User, size: int, difficulty: str):
        super().__init__(timeout=180)
        self.player = player
        self.size = size  # 3 또는 6
        self.win_req = 3 if size == 3 else 4  # 승리 조건 (3x3은 3줄, 6x6은 4줄 연속)
        self.difficulty = difficulty  # 'easy', 'normal', 'hard'
        
        self.current_round = 1
        self.p_wins = 0
        self.b_wins = 0

        self.reset_board()

    def reset_board(self):
        self.clear_items()
        self.board = [[0 for _ in range(self.size)] for _ in range(self.size)]
        
        for y in range(self.size):
            for x in range(self.size):
                if self.size == 6 and (x >= 5 or y >= 5): 
                    continue # 디스코드 버튼 최대 25개 제한으로 5x5 그리드로 보정
                self.add_item(TicTacToeButton(x, y))

    def is_board_full(self) -> bool:
        limit = min(self.size, 5)
        for y in range(limit):
            for x in range(limit):
                if self.board[y][x] == 0:
                    return False
        return True

    def check_winner(self, mark: int, board_state=None) -> bool:
        b = board_state if board_state is not None else self.board
        limit = min(self.size, 5)
        req = self.win_req

        for r in range(limit):
            for c in range(limit):
                # 가로
                if c + req <= limit and all(b[r][c+i] == mark for i in range(req)):
                    return True
                # 세로
                if r + req <= limit and all(b[r+i][c] == mark for i in range(req)):
                    return True
                # 대각선 ↘
                if r + req <= limit and c + req <= limit and all(b[r+i][c+i] == mark for i in range(req)):
                    return True
                # 대각선 ↙
                if r + req <= limit and c - req + 1 >= 0 and all(b[r+i][c-i] == mark for i in range(req)):
                    return True
        return False

    def bot_move(self):
        empty_cells = []
        limit = min(self.size, 5)
        for y in range(limit):
            for x in range(limit):
                if self.board[y][x] == 0:
                    empty_cells.append((x, y))

        if not empty_cells:
            return

        target_move = None

        # ----------------------------------
        # AI 난이도별 스마트 로직
        # ----------------------------------
        if self.difficulty in ['normal', 'hard']:
            # 1. AI가 이번 수로 이길 수 있는지 체크 (공격)
            for x, y in empty_cells:
                self.board[y][x] = 2
                if self.check_winner(2):
                    target_move = (x, y)
                    self.board[y][x] = 0
                    break
                self.board[y][x] = 0

            # 2. 유저가 다음 수로 이기는 것을 방어 (블로킹)
            if not target_move:
                for x, y in empty_cells:
                    self.board[y][x] = 1
                    if self.check_winner(1):
                        target_move = (x, y)
                        self.board[y][x] = 0
                        break
                    self.board[y][x] = 0

        if self.difficulty == 'hard' and not target_move:
            # 3. 어려움 난이도: 중앙 선점 시도
            center = limit // 2
            if (center, center) in empty_cells:
                target_move = (center, center)
            else:
                # 모서리 선점 시도
                corners = [(0, 0), (0, limit - 1), (limit - 1, 0), (limit - 1, limit - 1)]
                available_corners = [c for c in corners if c in empty_cells]
                if available_corners:
                    target_move = random.choice(available_corners)

        # 결정된 위치가 없으면 랜덤 선택
        if not target_move:
            target_move = random.choice(empty_cells)

        x, y = target_move
        self.board[y][x] = 2

        # 버튼 UI 업데이트
        for item in self.children:
            if isinstance(item, TicTacToeButton) and item.x == x and item.y == y:
                item.style = discord.ButtonStyle.success
                item.label = "⭕"
                item.disabled = True
                break

    def make_embed(self, msg: str = "") -> discord.Embed:
        diff_name = {"easy": "쉬움 🟢", "normal": "보통 🟡", "hard": "어려움 🔴"}.get(self.difficulty, "보통")
        embed = discord.Embed(
            title=f"🎮 틱택토 ({self.size}x{self.size}) - [난이도: {diff_name}]",
            color=discord.Color.blue()
        )
        embed.description = f"{msg}\n\n📌 **현재:** `{self.current_round}/3 라운드`\n👤 **{self.player.display_name}**: `{self.p_wins}승` | 🤖 **AI**: `{self.b_wins}승`"
        embed.set_footer(text="❌ : 유저 | ⭕ : AI")
        return embed

    async def next_round(self, interaction: discord.Interaction, round_msg: str):
        if self.p_wins == 2 or self.b_wins == 2 or self.current_round == 3:
            for item in self.children:
                item.disabled = True

            final_msg = ""
            if self.p_wins > self.b_wins:
                final_msg = "🏆 **최종 승리! 플레이어가 대결에서 이겼습니다!**"
                self.record_result(self.player.id, "win")
            elif self.b_wins > self.p_wins:
                final_msg = "💀 **최종 패배! AI가 대결에서 이겼습니다!**"
                self.record_result(self.player.id, "loss")
            else:
                final_msg = "🤝 **최종 무승부! 경기 결과가 비겼습니다.**"
                self.record_result(self.player.id, "draw")

            embed = self.make_embed(f"{round_msg}\n\n{final_msg}")
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
        else:
            self.current_round += 1
            self.reset_board()
            embed = self.make_embed(f"{round_msg}\n\n➡️ **{self.current_round}라운드를 시작합니다!**")
            await interaction.response.edit_message(embed=embed, view=self)

    def record_result(self, user_id: int, result: str):
        cursor.execute('SELECT wins, losses, draws FROM tictactoe_stats WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()

        if row is None:
            w, l, d = (1 if result == "win" else 0, 1 if result == "loss" else 0, 1 if result == "draw" else 0)
            cursor.execute('INSERT INTO tictactoe_stats (user_id, wins, losses, draws) VALUES (?, ?, ?, ?)',
                           (user_id, w, l, d))
        else:
            w, l, d = row
            if result == "win": w += 1
            elif result == "loss": l += 1
            elif result == "draw": d += 1
            cursor.execute('UPDATE tictactoe_stats SET wins = ?, losses = ?, draws = ? WHERE user_id = ?',
                           (w, l, d, user_id))
        conn.commit()


# --------------------------------------------------
# [명령어] /틱택토 및 /틱택토승률
# --------------------------------------------------

@bot.tree.command(name="틱택토", description="AI와 틱택토 3라운드 대결을 진행합니다.")
@app_commands.describe(판크기="게임판 크기를 선택하세요.", 난이도="AI의 난이도를 선택하세요.")
@app_commands.choices(
    판크기=[
        app_commands.Choice(name="3x3 (기본)", value="3"),
        app_commands.Choice(name="6x6 (확장)", value="6")
    ],
    난이도=[
        app_commands.Choice(name="쉬움 (랜덤 수)", value="easy"),
        app_commands.Choice(name="보통 (공격/방어)", value="normal"),
        app_commands.Choice(name="어려움 (스마트 AI)", value="hard")
    ]
)
async def tictactoe_start(
    interaction: discord.Interaction, 
    판크기: app_commands.Choice[str], 
    난이도: app_commands.Choice[str]
):
    size = int(판크기.value)
    diff = 난이도.value
    view = TicTacToeView(interaction.user, size, diff)
    embed = view.make_embed("게임이 시작되었습니다! 먼저 ❌를 둘 위치를 선택하세요.")
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="틱택토승률", description="나 또는 다른 유저의 틱택토 전적 및 승률을 조회합니다.")
@app_commands.describe(유저="전적을 조회할 유저 (선택)")
async def tictactoe_stats(interaction: discord.Interaction, 유저: discord.User = None):
    target = 유저 or interaction.user

    cursor.execute('SELECT wins, losses, draws FROM tictactoe_stats WHERE user_id = ?', (target.id,))
    row = cursor.fetchone()

    wins, losses, draws = row if row else (0, 0, 0)
    total_games = wins + losses + draws

    win_rate = (wins / total_games * 100) if total_games > 0 else 0.0

    embed = discord.Embed(title="📊 틱택토 전적 정보", color=discord.Color.purple())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="유저", value=target.mention, inline=False)
    embed.add_field(name="총 경기 수", value=f"**{total_games}전**", inline=True)
    embed.add_field(name="승 / 패 / 무", value=f"**{wins}승 {losses}패 {draws}무**", inline=True)
    embed.add_field(name="승률", value=f"**{win_rate:.1f}%**", inline=False)
    embed.set_footer(text=f"요청자: {interaction.user.display_name}")

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


@bot.tree.command(name="경고", description="유저에게 경고를 부여합니다.")
@app_commands.describe(유저="경고를 줄 유저", 횟수="부여할 경고 횟수 (기본값: 1)", 사유="경고 사유 (선택)")
@app_commands.checks.has_permissions(administrator=True)
async def give_warning(interaction: discord.Interaction, 유저: discord.Member, 횟수: int = 1, 사유: str = "사유 미기재"):
    if 횟수 <= 0:
        await interaction.response.send_message("❌ 경고 횟수는 1회 이상이어야 합니다.", ephemeral=True)
        return

    cursor.execute('SELECT warnings FROM warnings WHERE user_id = ?', (유저.id,))
    result = cursor.fetchone()

    if result is None:
        new_warns = 횟수
        cursor.execute('INSERT INTO warnings (user_id, warnings) VALUES (?, ?)', (유저.id, new_warns))
    else:
        new_warns = result[0] + 횟수
        cursor.execute('UPDATE warnings SET warnings = ? WHERE user_id = ?', (new_warns, 유저.id))
    
    conn.commit()

    embed = discord.Embed(title="⚠️ 경고 부여", color=discord.Color.red())
    embed.add_field(name="대상 유저", value=유저.mention, inline=True)
    embed.add_field(name="부여된 경고", value=f"**+{횟수}회**", inline=True)
    embed.add_field(name="누적 경고", value=f"**{new_warns}회**", inline=True)
    embed.add_field(name="사유", value=사유, inline=False)
    embed.set_footer(text=f"처리자: {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="경고차감", description="유저의 경고를 차감합니다.")
@app_commands.describe(유저="경고를 차감할 유저", 횟수="차감할 경고 횟수")
@app_commands.checks.has_permissions(administrator=True)
async def remove_warning(interaction: discord.Interaction, 유저: discord.Member, 횟수: int):
    if 횟수 <= 0:
        await interaction.response.send_message("❌ 차감할 횟수는 1회 이상이어야 합니다.", ephemeral=True)
        return

    cursor.execute('SELECT warnings FROM warnings WHERE user_id = ?', (유저.id,))
    result = cursor.fetchone()

    current_warns = result[0] if result else 0
    new_warns = max(0, current_warns - 횟수)

    cursor.execute('INSERT INTO warnings (user_id, warnings) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET warnings = ?', 
                   (유저.id, new_warns, new_warns))
    conn.commit()

    embed = discord.Embed(title="🟢 경고 차감", color=discord.Color.green())
    embed.add_field(name="대상 유저", value=유저.mention, inline=True)
    embed.add_field(name="차감된 경고", value=f"**-{횟수}회**", inline=True)
    embed.add_field(name="현재 누적 경고", value=f"**{new_warns}회**", inline=True)
    embed.set_footer(text=f"처리자: {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="경고수", description="나 또는 다른 유저의 누적 경고 수를 확인합니다.")
@app_commands.describe(유저="경고를 조회할 유저 (선택)")
async def check_warning(interaction: discord.Interaction, 유저: discord.User = None):
    target = 유저 or interaction.user

    cursor.execute('SELECT warnings FROM warnings WHERE user_id = ?', (target.id,))
    result = cursor.fetchone()
    warns = result[0] if result else 0

    embed = discord.Embed(title="🚨 경고 조회", color=discord.Color.orange())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="유저", value=target.mention, inline=True)
    embed.add_field(name="누적 경고", value=f"**{warns}회**", inline=True)
    embed.set_footer(text=f"요청자: {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)


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
