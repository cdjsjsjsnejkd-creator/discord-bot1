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
    t.daemon = True
    t.start()

TOKEN = os.getenv("TOKEN")

# --------------------------------------------------
# [DB 설정] SQLite 데이터베이스 연결 및 테이블 생성
# --------------------------------------------------
conn = sqlite3.connect('points.db', check_same_thread=False)
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
        earned = float(random.randint(5, 15))
        cursor.execute('INSERT INTO users (user_id, points, last_chat) VALUES (?, ?, ?)',
                       (user_id, earned, current_time))
        conn.commit()
    else:
        points, last_chat = result
        if current_time - last_chat >= CHAT_COOLDOWN:
            earned = float(random.randint(5, 15))
            cursor.execute('UPDATE users SET points = points + ?, last_chat = ? WHERE user_id = ?',
                           (earned, current_time, user_id))
            conn.commit()

    await bot.process_commands(message)

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

        loss_amount = round(self.bet * 0.5, 2)
        win_reward = round(self.bet, 2)

        embed = discord.Embed(title=title, color=discord.Color.gold() if not end else discord.Color.dark_purple())
        embed.set_author(name=self.player.display_name, icon_url=self.player.display_avatar.url)
        embed.add_field(name="💰 베팅 정보", value=f"베팅금: **{self.bet:,.2f}** PT\n(승리 시 **+{win_reward:,.2f}** PT / 패배 시 50% 환불로 **-{loss_amount:,.2f}** PT)", inline=False)
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
            loss_amount = round(self.bet * 0.5, 2)
            cursor.execute('UPDATE users SET points = MAX(0, points - ?) WHERE user_id = ?', (loss_amount, self.player.id))
            conn.commit()

            for child in self.children:
                child.disabled = True

            embed = self.make_embed(title="💥 버스트! (100점 초과 패배)", end=True)
            embed.add_field(name="결과", value=f"💀 100점을 초과하여 패배했습니다.\n🔻 베팅금의 50%인 **-{loss_amount:,.2f}** PT가 차감되었습니다. (50% 환불)", inline=False)
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
        win_amount = round(self.bet, 2)
        loss_amount = round(self.bet * 0.5, 2)

        if d_score > 100 or p_score > d_score:
            cursor.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (win_amount, self.player.id))
            conn.commit()
            result_msg = f"🏆 승리했습니다!\n🔺 **+{win_amount:,.2f}** PT 획득!"
        elif p_score < d_score:
            cursor.execute('UPDATE users SET points = MAX(0, points - ?) WHERE user_id = ?', (loss_amount, self.player.id))
            conn.commit()
            result_msg = f"💀 패배했습니다...\n🔻 베팅금의 50%인 **-{loss_amount:,.2f}** PT가 차감되었습니다. (50% 환불)"
        else:
            result_msg = "🤝 무승부입니다! 베팅금이 보존됩니다."

        embed = self.make_embed(title="🎲 게임 종료", end=True)
        embed.add_field(name="결과", value=result_msg, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

# --------------------------------------------------
# [블랙잭 - 플레이어 대전(1v1) View]
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
        self.current_turn = p1

    def make_embed(self, title="⚔️ 1v1 블랙잭 대전", end=False):
        s1 = calculate_score(self.p1_hand)
        s2 = calculate_score(self.p2_hand)

        embed = discord.Embed(title=title, color=discord.Color.red() if end else discord.Color.blue())
        embed.add_field(name="💰 판돈", value=f"각각 **{self.bet:,.2f}** PT (승자 **+{self.bet:,.2f}** PT 획득 / 패자 **-{self.bet*0.5:,.2f}** PT 손실)", inline=False)
        
        embed.add_field(name=f"👤 {self.p1.display_name} ({s1}점)", value=render_cards(self.p1_hand), inline=True)
        embed.add_field(name=f"👤 {self.p2.display_name} ({s2}점)", value=render_cards(self.p2_hand), inline=True)

        if not end:
            embed.add_field(name="🎯 현재 차례", value=f"**{self.current_turn.mention}** 님의 순서입니다.", inline=False)

        return embed

    async def check_next_turn(self, interaction: discord.Interaction):
        if self.p1_done and self.p2_done:
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
                loss_amount = round(self.bet * 0.5, 2)
                cursor.execute('UPDATE users SET points = MAX(0, points - ?) WHERE user_id = ?', (loss_amount, loser.id))
                cursor.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (self.bet, winner.id))
                conn.commit()
                msg = f"🏆 **{winner.mention}** 님이 승리하여 **+{self.bet:,.2f} PT**를 획득했습니다!\n(패배자 **-{loss_amount:,.2f} PT** 차감)"

            embed = self.make_embed(title="🎲 대전 종료", end=True)
            embed.add_field(name="결과", value=msg, inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
        else:
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

# --------------------------------------------------
# [1v1 대전 매칭 대기열 View]
# --------------------------------------------------
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
        self.turn = 1

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
# [틱택토 - 봇(AI) 대전 View]
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
# [슬래시 명령어] 게임 시작 명령어
# --------------------------------------------------

@bot.tree.command(name="블랙잭", description="포인트를 걸고 블랙잭 게임을 합니다.")
@app_commands.describe(
    상대="대결 상대 선택 (봇 또는 다른 플레이어)",
    베팅금액="베팅할 포인트 금액 (최소 10 PT 이상)"
)
@app_commands.choices(
    상대=[
        app_commands.Choice(name="🤖 봇 (AI 대전 - 최대 50 PT)", value="bot"),
        app_commands.Choice(name="⚔️ 플레이어 대전 (1v1 매칭)", value="player")
    ]
)
async def blackjack_start(interaction: discord.Interaction, 상대: app_commands.Choice[str], 베팅금액: float):
    베팅금액 = round(베팅금액, 2)
    if 베팅금액 < 10.0:
        await interaction.response.send_message("❌ 블랙잭은 최소 **10 PT**부터 시작할 수 있습니다.", ephemeral=True)
        return

    if 상대.value == "bot" and 베팅금액 > 50.0:
        await interaction.response.send_message("❌ 봇(AI) 대전은 최대 **50 PT**까지만 베팅할 수 있습니다!", ephemeral=True)
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


@bot.tree.command(name="블랙잭설명", description="블랙잭 게임의 규칙 및 이용법을 확인합니다.")
async def blackjack_info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🃏 블랙잭 게임 가이드 및 규칙",
        description="카드의 합이 **100**을 초과하지 않으면서 상대보다 **100에 가까운 점수**를 만들면 승리하는 게임입니다.",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="📌 주요 규칙 요약",
        value=(
            "• **베팅금 제한:** 최소 `10 PT` 이상 (※ **봇 대전은 최대 50 PT**까지 가능)\n"
            "• **상대 선택:** AI 봇 대전 또는 플레이어간 1v1 대전 선택 가능\n"
            "• **히트 (Hit):** 카드를 1장 더 뽑습니다.\n"
            "• **스탠드 (Stand):** 현재 카드로 점수를 겨룹니다.\n"
            "• **딜러 AI 규칙:** 딜러는 점수가 `85점` 이상이 될 때까지 자동으로 카드를 뽑습니다."
        ),
        inline=False
    )
    embed.add_field(
        name="🔢 카드 점수 계산법",
        value=(
            "• **2 ~ 10:** 카드 표기 숫자 그대로 계산\n"
            "• **J, Q, K:** 각각 `10점`으로 계산\n"
            "• **A (Ace):** 100점을 넘지 않으면 `11점`, 넘어가면 `1점`으로 자동 변경"
        ),
        inline=False
    )
    embed.add_field(
        name="💰 승패 및 포인트 배율",
        value=(
            "• **승리:** 베팅금만큼 추가 획득 (+100%)\n"
            "• **무승부:** 베팅금을 그대로 보존\n"
            "• **패배:** 베팅금의 **50%만 손실** (나머지 50%는 환불)"
        ),
        inline=False
    )
    embed.set_footer(text=f"요청자: {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)


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
# [관리자 전용] 포인트 지급 & 차감
# --------------------------------------------------

@bot.tree.command(name="포인트지급", description="[관리자 전용] 지정한 유저에게 포인트를 지급합니다.")
@app_commands.describe(유저="포인트를 받게 될 유저", 지급액="지급할 포인트 양")
@app_commands.checks.has_permissions(administrator=True)
async def give_points(interaction: discord.Interaction, 유저: discord.Member, 지급액: float):
    if 지급액 <= 0:
        await interaction.response.send_message("❌ 지급할 포인트는 0보다 커야 합니다.", ephemeral=True)
        return

    지급액 = round(지급액, 2)
    cursor.execute('SELECT points FROM users WHERE user_id = ?', (유저.id,))
    result = cursor.fetchone()

    if result is None:
        new_points = 지급액
        cursor.execute('INSERT INTO users (user_id, points, last_chat) VALUES (?, ?, ?)', (유저.id, new_points, time.time()))
    else:
        new_points = round(result[0] + 지급액, 2)
        cursor.execute('UPDATE users SET points = ? WHERE user_id = ?', (new_points, 유저.id))

    conn.commit()

    embed = discord.Embed(title="🪙 포인트 지급 완료", color=discord.Color.gold())
    embed.set_thumbnail(url=유저.display_avatar.url)
    embed.add_field(name="지급 대상", value=유저.mention, inline=True)
    embed.add_field(name="지급 금액", value=f"**+{지급액:,.2f}** PT", inline=True)
    embed.add_field(name="보유 포인트", value=f"**{new_points:,.2f}** PT", inline=False)
    embed.set_footer(text=f"처리자: {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="포인트차감", description="[관리자 전용] 지정한 유저의 포인트를 차감합니다.")
@app_commands.describe(유저="포인트를 차감할 유저", 차감액="차감할 포인트 양")
@app_commands.checks.has_permissions(administrator=True)
async def remove_points(interaction: discord.Interaction, 유저: discord.Member, 차감액: float):
    if 차감액 <= 0:
        await interaction.response.send_message("❌ 차감할 포인트는 0보다 커야 합니다.", ephemeral=True)
        return

    차감액 = round(차감액, 2)
    cursor.execute('SELECT points FROM users WHERE user_id = ?', (유저.id,))
    result = cursor.fetchone()

    current_points = float(result[0]) if result else 0.0
    new_points = max(0.0, round(current_points - 차감액, 2))

    cursor.execute('INSERT INTO users (user_id, points, last_chat) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET points = ?', 
                   (유저.id, new_points, time.time(), new_points))
    conn.commit()

    embed = discord.Embed(title="🔻 포인트 차감 완료", color=discord.Color.red())
    embed.set_thumbnail(url=유저.display_avatar.url)
    embed.add_field(name="차감 대상", value=유저.mention, inline=True)
    embed.add_field(name="차감 금액", value=f"**-{차감액:,.2f}** PT", inline=True)
    embed.add_field(name="현재 보유 포인트", value=f"**{new_points:,.2f}** PT", inline=False)
    embed.set_footer(text=f"처리자: {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)

# --------------------------------------------------
# [기타 서버 관리 & 유틸리티 명령어 모음]
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
    pts = float(result[0]) if result else 0.0

    embed = discord.Embed(title="🪙 포인트 정보", color=discord.Color.gold())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="유저", value=target.mention, inline=True)
    embed.add_field(name="보유 포인트", value=f"**{pts:,.2f}** PT", inline=True)
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
        rank_text += f"{medal} <@{user_id}> - **{float(pts):,.2f}** PT\n"

    embed.description = rank_text
    embed.set_footer(text=f"요청자: {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

# --------------------------------------------------
# [봇 실행]
# --------------------------------------------------
if __name__ == "__main__":
    if TOKEN:
        keep_alive()
        bot.run(TOKEN)
    else:
        print("❌ 에러: TOKEN 환경변수가 설정되지 않았습니다.")
