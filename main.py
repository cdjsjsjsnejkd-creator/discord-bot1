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
# [DB 설정]
# --------------------------------------------------
conn = sqlite3.connect('points.db')
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        points REAL DEFAULT 0,
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
# [Intents 및 Bot 설정]
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
# [공통 카드 유틸]
# --------------------------------------------------
SUITS = ['♠️', '♥️', '♦️', '♣️']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

def calculate_score(cards):
    score = 0
    aces = 0
    for suit, rank in cards:
        if rank in ['J', 'Q', 'K']:
            score += 10
        elif rank == 'A':
            aces += 1
            score += 11
        else:
            score += int(rank)
    while score > 100 and aces:
        score -= 10
        aces -= 1
    return score

def render_cards(cards):
    return " ".join([f"`{suit}{rank}`" for suit, rank in cards])

# --------------------------------------------------
# [블랙잭 - 봇(AI) 대전 View]
# --------------------------------------------------
class BlackjackBotView(discord.ui.View):
    def __init__(self, player: discord.User, bet: float):
        super().__init__(timeout=60)
        self.player = player
        self.bet = round(bet, 2)
        self.deck = [(s, r) for s in SUITS for r in RANKS]
        random.shuffle(self.deck)

        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]

    def make_embed(self, title="🃏 100점 블랙잭 (vs AI)", end=False):
        p_score = calculate_score(self.player_hand)
        d_score = calculate_score(self.dealer_hand)

        cursor.execute('SELECT points FROM users WHERE user_id = ?', (self.player.id,))
        row = cursor.fetchone()
        current_pts = float(row[0]) if row else 0.0
        potential_loss = round(current_pts * 0.5, 2)
        win_reward = round(self.bet * 2, 2)

        embed = discord.Embed(title=title, color=discord.Color.gold() if not end else discord.Color.dark_purple())
        embed.set_author(name=self.player.display_name, icon_url=self.player.display_avatar.url)
        embed.add_field(name="💰 베팅금액", value=f"**{self.bet:,.2f}** PT (승리 시 **+{win_reward:,.2f}** / 패배 시 **-{potential_loss:,.2f}** PT)", inline=False)
        embed.add_field(name=f"👤 플레이어 카드 ({p_score}점 / 100점)", value=render_cards(self.player_hand), inline=False)
        
        if end:
            embed.add_field(name=f"🤖 딜러 카드 ({d_score}점 / 100점)", value=render_cards(self.dealer_hand), inline=False)
        else:
            embed.add_field(name="🤖 딜러 카드", value=f"{render_cards([self.dealer_hand[0]])} `❓`", inline=False)
        return embed

    @discord.ui.button(label="히트 (Hit)", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.player:
            await interaction.response.send_message("❌ 본인의 게임만 조작할 수 있습니다.", ephemeral=True)
            return

        self.player_hand.append(self.deck.pop())
        p_score = calculate_score(self.player_hand)

        if p_score > 100:
            cursor.execute('SELECT points FROM users WHERE user_id = ?', (self.player.id,))
            row = cursor.fetchone()
            current_pts = float(row[0]) if row else 0.0
            loss_amount = round(current_pts * 0.5, 2)

            cursor.execute('UPDATE users SET points = MAX(0, points - ?) WHERE user_id = ?', (loss_amount, self.player.id))
            conn.commit()

            for child in self.children:
                child.disabled = True

            embed = self.make_embed(title="💥 버스트! (100점 초과 패배)", end=True)
            embed.add_field(name="결과", value=f"💀 100점을 초과하여 패배했습니다.\n🔻 **-{loss_amount:,.2f}** PT가 차감되었습니다.", inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
        else:
            await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="스탠드 (Stand)", style=discord.ButtonStyle.success, emoji="✋")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.player:
            await interaction.response.send_message("❌ 본인의 게임만 조작할 수 있습니다.", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True

        while calculate_score(self.dealer_hand) < 85:
            self.dealer_hand.append(self.deck.pop())

        p_score = calculate_score(self.player_hand)
        d_score = calculate_score(self.dealer_hand)
        win_amount = round(self.bet * 2, 2)

        if d_score > 100 or p_score > d_score:
            cursor.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (win_amount, self.player.id))
            conn.commit()
            result_msg = f"🏆 승리했습니다!\n🔺 베팅금의 2배인 **+{win_amount:,.2f}** PT 획득!"
        elif p_score < d_score:
            cursor.execute('SELECT points FROM users WHERE user_id = ?', (self.player.id,))
            row = cursor.fetchone()
            current_pts = float(row[0]) if row else 0.0
            loss_amount = round(current_pts * 0.5, 2)

            cursor.execute('UPDATE users SET points = MAX(0, points - ?) WHERE user_id = ?', (loss_amount, self.player.id))
            conn.commit()
            result_msg = f"💀 패배했습니다...\n🔻 보유 포인트의 50%인 **-{loss_amount:,.2f}** PT가 차감되었습니다."
        else:
            result_msg = "🤝 무승부입니다! 베팅금이 보존됩니다."

        embed = self.make_embed(title="🎲 게임 종료", end=True)
        embed.add_field(name="결과", value=result_msg, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

# --------------------------------------------------
# [블랙잭 - 플레이어 대전(1v1) View 및 대기열]
# --------------------------------------------------
class BlackjackPVPView(discord.ui.View):
    def __init__(self, p1: discord.User, p2: discord.User, bet: float):
        super().__init__(timeout=120)
        self.p1 = p1
        self.p2 = p2
        self.bet = round(bet, 2)
        
        self.deck = [(s, r) for s in SUITS for r in RANKS]
        random.shuffle(self.deck)

        self.p1_hand = [self.deck.pop(), self.deck.pop()]
        self.p2_hand = [self.deck.pop(), self.deck.pop()]
        
        self.p1_done = False
        self.p2_done = False
        self.current_turn = p1  # P1 선공

    def make_embed(self, title="⚔️ 1v1 블랙잭 대전", end=False):
        s1 = calculate_score(self.p1_hand)
        s2 = calculate_score(self.p2_hand)

        embed = discord.Embed(title=title, color=discord.Color.red() if end else discord.Color.blue())
        embed.add_field(name="💰 판돈", value=f"각각 **{self.bet:,.2f}** PT (승자 **+{self.bet*2:,.2f}** PT 획득)", inline=False)
        
        embed.add_field(name=f"👤 {self.p1.display_name} ({s1}점)", value=render_cards(self.p1_hand), inline=True)
        embed.add_field(name=f"👤 {self.p2.display_name} ({s2}점)", value=render_cards(self.p2_hand), inline=True)

        if not end:
            embed.add_field(name="🎯 현재 차례", value=f"**{self.current_turn.mention}** 님의 순서입니다.", inline=False)

        return embed

    async def check_next_turn(self, interaction: discord.Interaction):
        if self.p1_done and self.p2_done:
            # 둘 다 완료 -> 결과 처리
            for child in self.children:
                child.disabled = True

            s1 = calculate_score(self.p1_hand)
            s2 = calculate_score(self.p2_hand)

            p1_bust = s1 > 100
            p2_bust = s2 > 100

            winner = None
            if p1_bust and p2_bust:
                msg = "💥 둘 다 100점 초과 버스트로 무승부 처리되었습니다."
            elif p1_bust:
                winner = self.p2
            elif p2_bust:
                winner = self.p1
            elif s1 > s2:
                winner = self.p1
            elif s2 > s1:
                winner = self.p2
            else:
                msg = "🤝 점수가 같아 무승부로 처리되었습니다!"

            if winner:
                loser = self.p2 if winner == self.p1 else self.p1
                # 베팅금 정산
                cursor.execute('UPDATE users SET points = MAX(0, points - ?) WHERE user_id = ?', (self.bet, loser.id))
                cursor.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (self.bet, winner.id))
                conn.commit()
                msg = f"🏆 **{winner.mention}** 님이 승리하여 **+{self.bet:,.2f} PT**를 획득했습니다!"

            embed = self.make_embed(title="🎲 대전 종료", end=True)
            embed.add_field(name="결과", value=msg, inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
        else:
            # 턴 교체
            if self.current_turn == self.p1 and not self.p2_done:
                self.current_turn = self.p2
            elif self.current_turn == self.p2 and not self.p1_done:
                self.current_turn = self.p1

            await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="히트 (Hit)", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.current_turn:
            await interaction.response.send_message("❌ 지금은 본인의 차례가 아닙니다!", ephemeral=True)
            return

        if interaction.user == self.p1:
            self.p1_hand.append(self.deck.pop())
            if calculate_score(self.p1_hand) > 100:
                self.p1_done = True
        else:
            self.p2_hand.append(self.deck.pop())
            if calculate_score(self.p2_hand) > 100:
                self.p2_done = True

        await self.check_next_turn(interaction)

    @discord.ui.button(label="스탠드 (Stand)", style=discord.ButtonStyle.success, emoji="✋")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.current_turn:
            await interaction.response.send_message("❌ 지금은 본인의 차례가 아닙니다!", ephemeral=True)
            return

        if interaction.user == self.p1:
            self.p1_done = True
        else:
            self.p2_done = True

        await self.check_next_turn(interaction)


class MatchWaitView(discord.ui.View):
    def __init__(self, host: discord.User, game_type: str, bet: float = 0.0, size: int = 3):
        super().__init__(timeout=180)
        self.host = host
        self.game_type = game_type
        self.bet = bet
        self.size = size

    @discord.ui.button(label="⚔️ 대전 수락 (매치)", style=discord.ButtonStyle.danger)
    async def accept_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user == self.host:
            await interaction.response.send_message("❌ 자신이 올린 매칭은 본인이 수락할 수 없습니다.", ephemeral=True)
            return

        # 블랙잭 포인트 확인
        if self.game_type == "blackjack":
            cursor.execute('SELECT points FROM users WHERE user_id = ?', (interaction.user.id,))
            row = cursor.fetchone()
            pts = float(row[0]) if row else 0.0
            if pts < self.bet:
                await interaction.response.send_message(f"❌ 포인트가 부족합니다. (필요: **{self.bet:,.2f}** PT)", ephemeral=True)
                return

            view = BlackjackPVPView(self.host, interaction.user, self.bet)
            embed = view.make_embed()
            await interaction.response.edit_message(content=f"⚔️ **{self.host.mention} vs {interaction.user.mention}** 매치 성사!", embed=embed, view=view)
        
        elif self.game_type == "tictactoe":
            view = TicTacToePVPView(self.host, interaction.user, self.size)
            embed = view.make_embed("게임이 시작되었습니다! 먼저 ❌(P1)를 둘 위치를 선택하세요.")
            await interaction.response.edit_message(content=f"🎮 **{self.host.mention} vs {interaction.user.mention}** 틱택토 대전!", embed=embed, view=view)

        self.stop()


# --------------------------------------------------
# [틱택토 - 플레이어 대전(1v1) View]
# --------------------------------------------------
class TicTacToePVPButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        assert self.view is not None
        view: TicTacToePVPView = self.view

        current_player = view.p1 if view.turn == 1 else view.p2
        if interaction.user != current_player:
            await interaction.response.send_message("❌ 본인의 차례가 아닙니다!", ephemeral=True)
            return

        if view.board[self.y][self.x] != 0:
            await interaction.response.send_message("❌ 이미 선택된 칸입니다!", ephemeral=True)
            return

        mark = view.turn
        view.board[self.y][self.x] = mark
        self.style = discord.ButtonStyle.danger if mark == 1 else discord.ButtonStyle.success
        self.label = "❌" if mark == 1 else "⭕"
        self.disabled = True

        if view.check_winner(mark):
            if mark == 1: view.p1_wins += 1
            else: view.p2_wins += 1
            await view.next_round(interaction, f"🎉 **{view.current_round}라운드 {current_player.display_name} 승리!**")
            return

        if view.is_board_full():
            await view.next_round(interaction, f"🤝 **{view.current_round}라운드 무승부!**")
            return

        view.turn = 2 if view.turn == 1 else 1
        await interaction.response.edit_message(embed=view.make_embed(), view=view)


class TicTacToePVPView(discord.ui.View):
    def __init__(self, p1: discord.User, p2: discord.User, size: int):
        super().__init__(timeout=180)
        self.p1 = p1
        self.p2 = p2
        self.size = size
        self.win_req = 3 if size == 3 else 4
        self.turn = 1 # 1: P1(X), 2: P2(O)

        self.current_round = 1
        self.p1_wins = 0
        self.p2_wins = 0

        self.reset_board()

    def reset_board(self):
        self.clear_items()
        self.board = [[0 for _ in range(self.size)] for _ in range(self.size)]
        for y in range(self.size):
            for x in range(self.size):
                if self.size == 6 and (x >= 5 or y >= 5): continue
                self.add_item(TicTacToePVPButton(x, y))

    def is_board_full(self) -> bool:
        limit = min(self.size, 5)
        for y in range(limit):
            for x in range(limit):
                if self.board[y][x] == 0: return False
        return True

    def check_winner(self, mark: int) -> bool:
        limit = min(self.size, 5)
        req = self.win_req
        b = self.board
        for r in range(limit):
            for c in range(limit):
                if c + req <= limit and all(b[r][c+i] == mark for i in range(req)): return True
                if r + req <= limit and all(b[r+i][c] == mark for i in range(req)): return True
                if r + req <= limit and c + req <= limit and all(b[r+i][c+i] == mark for i in range(req)): return True
                if r + req <= limit and c - req + 1 >= 0 and all(b[r+i][c-i] == mark for i in range(req)): return True
        return False

    def make_embed(self, msg: str = "") -> discord.Embed:
        curr = self.p1 if self.turn == 1 else self.p2
        embed = discord.Embed(title=f"🎮 틱택토 1v1 대전 ({self.size}x{self.size})", color=discord.Color.purple())
        embed.description = f"{msg}\n\n📌 **현재:** `{self.current_round}/3 라운드`\n❌ **{self.p1.display_name}**: `{self.p1_wins}승` | ⭕ **{self.p2.display_name}**: `{self.p2_wins}승`"
        embed.add_field(name="🎯 현재 차례", value=f"**{curr.mention}** 님의 차례입니다.", inline=False)
        return embed

    async def next_round(self, interaction: discord.Interaction, round_msg: str):
        if self.p1_wins == 2 or self.p2_wins == 2 or self.current_round == 3:
            for item in self.children: item.disabled = True
            
            if self.p1_wins > self.p2_wins: final_msg = f"🏆 **최종 승리! {self.p1.mention} 님이 대결에서 이겼습니다!**"
            elif self.p2_wins > self.p1_wins: final_msg = f"🏆 **최종 승리! {self.p2.mention} 님이 대결에서 이겼습니다!**"
            else: final_msg = "🤝 **최종 무승부입니다!**"

            embed = self.make_embed(f"{round_msg}\n\n{final_msg}")
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
        else:
            self.current_round += 1
            self.reset_board()
            embed = self.make_embed(f"{round_msg}\n\n➡️ **{self.current_round}라운드를 시작합니다!**")
            await interaction.response.edit_message(embed=embed, view=self)


# --------------------------------------------------
# [슬래시 명령어] 블랙잭 & 틱택토
# --------------------------------------------------

@bot.tree.command(name="블랙잭", description="포인트를 걸고 블랙잭 게임을 합니다.")
@app_commands.describe(
    상대="대결 상대 선택 (봇 또는 다른 플레이어)",
    베팅금액="베팅할 포인트 금액 (최소 10 PT 이상)"
)
@app_commands.choices(
    상대=[
        app_commands.Choice(name="🤖 봇 (AI 대전)", value="bot"),
        app_commands.Choice(name="⚔️ 플레이어 대전 (1v1 매칭)", value="player")
    ]
)
async def blackjack_start(interaction: discord.Interaction, 상대: app_commands.Choice[str], 베팅금액: float):
    베팅금액 = round(베팅금액, 2)
    if 베팅금액 < 10.0:
        await interaction.response.send_message("❌ 블랙잭은 최소 **10 PT**부터 시작할 수 있습니다.", ephemeral=True)
        return

    cursor.execute('SELECT points FROM users WHERE user_id = ?', (interaction.user.id,))
    row = cursor.fetchone()
    current_pts = float(row[0]) if row else 0.0

    if current_pts < 베팅금액:
        await interaction.response.send_message(f"❌ 포인트가 부족합니다. (현재 보유: **{current_pts:,.2f}** PT)", ephemeral=True)
        return

    if 상대.value == "bot":
        view = BlackjackBotView(interaction.user, 베팅금액)
        embed = view.make_embed()
        await interaction.response.send_message(embed=embed, view=view)
    else:
        view = MatchWaitView(interaction.user, game_type="blackjack", bet=베팅금액)
        embed = discord.Embed(
            title="⚔️ 1v1 블랙잭 대전 매칭 대기 중...",
            description=f"**{interaction.user.mention}** 님이 **{베팅금액:,.2f} PT** 대전을 신청했습니다!\n아래 버튼을 누르면 즉시 1대1 매치가 시작됩니다.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="틱택토", description="틱택토 3라운드 대결을 진행합니다.")
@app_commands.describe(
    상대="대결 상대 선택 (봇 또는 다른 플레이어)",
    판크기="게임판 크기를 선택하세요.",
    난이도="[봇 대전 전용] AI 난이도"
)
@app_commands.choices(
    상대=[
        app_commands.Choice(name="🤖 봇 (AI 대전)", value="bot"),
        app_commands.Choice(name="⚔️ 플레이어 대전 (1v1 매칭)", value="player")
    ],
    판크기=[
        app_commands.Choice(name="3x3 (기본)", value="3"),
        app_commands.Choice(name="6x6 (확장)", value="6")
    ],
    난이도=[
        app_commands.Choice(name="쉬움", value="easy"),
        app_commands.Choice(name="보통", value="normal"),
        app_commands.Choice(name="어려움", value="hard")
    ]
)
async def tictactoe_start(
    interaction: discord.Interaction, 
    상대: app_commands.Choice[str],
    판크기: app_commands.Choice[str], 
    난이도: app_commands.Choice[str] = None
):
    size = int(판크기.value)

    if 상대.value == "bot":
        diff = 난이도.value if 난이도 else "normal"
        from __main__ import TicTacToeView # 기존 싱글 View 호출
        view = TicTacToeView(interaction.user, size, diff)
        embed = view.make_embed("게임이 시작되었습니다! 먼저 ❌를 둘 위치를 선택하세요.")
        await interaction.response.send_message(embed=embed, view=view)
    else:
        view = MatchWaitView(interaction.user, game_type="tictactoe", size=size)
        embed = discord.Embed(
            title="⚔️ 1v1 틱택토 대전 매칭 대기 중...",
            description=f"**{interaction.user.mention}** 님이 **{size}x{size}** 대전을 신청했습니다!\n아래 버튼을 누르면 즉시 1대1 매치가 시작됩니다.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, view=view)


# --------------------------------------------------
# [기존 틱택토 봇 전용 클래스 및 기타 시스템 유지]
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

        view.board[self.y][self.x] = 1
        self.style = discord.ButtonStyle.danger
        self.label = "❌"
        self.disabled = True

        if view.check_winner(1):
            view.p_wins += 1
            await view.next_round(interaction, f"🎉 **{view.current_round}라운드 승리!**")
            return

        if view.is_board_full():
            await view.next_round(interaction, f"🤝 **{view.current_round}라운드 무승부!**")
            return

        view.bot_move()

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
        self.size = size
        self.win_req = 3 if size == 3 else 4
        self.difficulty = difficulty
        self.current_round = 1
        self.p_wins = 0
        self.b_wins = 0
        self.reset_board()

    def reset_board(self):
        self.clear_items()
        self.board = [[0 for _ in range(self.size)] for _ in range(self.size)]
        for y in range(self.size):
            for x in range(self.size):
                if self.size == 6 and (x >= 5 or y >= 5): continue
                self.add_item(TicTacToeButton(x, y))

    def is_board_full(self) -> bool:
        limit = min(self.size, 5)
        for y in range(limit):
            for x in range(limit):
                if self.board[y][x] == 0: return False
        return True

    def check_winner(self, mark: int) -> bool:
        limit = min(self.size, 5)
        req = self.win_req
        b = self.board
        for r in range(limit):
            for c in range(limit):
                if c + req <= limit and all(b[r][c+i] == mark for i in range(req)): return True
                if r + req <= limit and all(b[r+i][c] == mark for i in range(req)): return True
                if r + req <= limit and c + req <= limit and all(b[r+i][c+i] == mark for i in range(req)): return True
                if r + req <= limit and c - req + 1 >= 0 and all(b[r+i][c-i] == mark for i in range(req)): return True
        return False

    def bot_move(self):
        empty_cells = []
        limit = min(self.size, 5)
        for y in range(limit):
            for x in range(limit):
                if self.board[y][x] == 0: empty_cells.append((x, y))

        if not empty_cells: return
        target_move = None

        if self.difficulty in ['normal', 'hard']:
            for x, y in empty_cells:
                self.board[y][x] = 2
                if self.check_winner(2):
                    target_move = (x, y)
                    self.board[y][x] = 0
                    break
                self.board[y][x] = 0

            if not target_move:
                for x, y in empty_cells:
                    self.board[y][x] = 1
                    if self.check_winner(1):
                        target_move = (x, y)
                        self.board[y][x] = 0
                        break
                    self.board[y][x] = 0

        if not target_move: target_move = random.choice(empty_cells)

        x, y = target_move
        self.board[y][x] = 2
        for item in self.children:
            if isinstance(item, TicTacToeButton) and item.x == x and item.y == y:
                item.style = discord.ButtonStyle.success
                item.label = "⭕"
                item.disabled = True
                break

    def make_embed(self, msg: str = "") -> discord.Embed:
        embed = discord.Embed(title=f"🎮 틱택토 vs AI ({self.size}x{self.size})", color=discord.Color.blue())
        embed.description = f"{msg}\n\n📌 **현재:** `{self.current_round}/3 라운드`\n👤 **{self.player.display_name}**: `{self.p_wins}승` | 🤖 **AI**: `{self.b_wins}승`"
        return embed

    async def next_round(self, interaction: discord.Interaction, round_msg: str):
        if self.p_wins == 2 or self.b_wins == 2 or self.current_round == 3:
            for item in self.children: item.disabled = True
            if self.p_wins > self.b_wins: final_msg = "🏆 **최종 승리! 플레이어가 대결에서 이겼습니다!**"
            elif self.b_wins > self.p_wins: final_msg = "💀 **최종 패배! AI가 대결에서 이겼습니다!**"
            else: final_msg = "🤝 **최종 무승부! 경기 결과가 비겼습니다.**"
            embed = self.make_embed(f"{round_msg}\n\n{final_msg}")
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
        else:
            self.current_round += 1
            self.reset_board()
            embed = self.make_embed(f"{round_msg}\n\n➡️ **{self.current_round}라운드를 시작합니다!**")
            await interaction.response.edit_message(embed=embed, view=self)

# --------------------------------------------------
# [포인트 및 기존 유틸리티 명령어 모음]
# --------------------------------------------------
@bot.tree.command(name="포인트", description="포인트를 확인합니다.")
async def check_points(interaction: discord.Interaction, 유저: discord.User = None):
    target = 유저 or interaction.user
    cursor.execute('SELECT points FROM users WHERE user_id = ?', (target.id,))
    result = cursor.fetchone()
    pts = float(result[0]) if result else 0.0
    await interaction.response.send_message(f"🪙 **{target.display_name}** 님의 보유 포인트: **{pts:,.2f}** PT")

# --------------------------------------------------
# [실행]
# --------------------------------------------------
if TOKEN:
    keep_alive()
    bot.run(TOKEN)
else:
    print("❌ 에러: TOKEN 환경변수가 설정되지 않았습니다.")
