import chess
import chess.engine
from models import db, Thread, Message

# Global Stockfish engine instance
_stockfish_engine = None

def get_stockfish_engine():
    """Get or create global Stockfish engine instance"""
    global _stockfish_engine
    if _stockfish_engine is None:
        try:
            # Update path if necessary
            _stockfish_engine = chess.engine.SimpleEngine.popen_uci(
                r".\stockfish\stockfish-windows-x86-64-avx2.exe"
            )
        except Exception as e:
            print(f"Failed to initialize Stockfish: {e}")
            return None
    return _stockfish_engine

def get_or_create_fen(thread_id):
    """Get existing FEN from thread or initialize new board"""
    thread = Thread.query.get(thread_id)
    if not thread:
        return None
    if thread.fen:
        return thread.fen
    else:
        board = chess.Board()
        thread.fen = board.fen()
        db.session.commit()
        return thread.fen

def process_move(fen, move_uci):
    """Process a chess move and return new FEN with Stockfish evaluation"""
    board = chess.Board(fen)
    if not move_uci:
        return fen, None, False, None

    try:
        move = board.parse_uci(move_uci)
        if move in board.legal_moves:
            board.push(move)
            new_fen = board.fen()
            game_over = board.is_game_over()
            result = board.result() if game_over else None

            evaluation_score = None
            engine = get_stockfish_engine()
            if engine:
                try:
                    info = engine.analyse(board, chess.engine.Limit(depth=15))
                    score_obj = info["score"].white()
                    if not score_obj.is_mate():
                        evaluation_score = score_obj.score()
                except Exception as e:
                    print(f"Stockfish evaluation failed: {e}")

            return new_fen, result, game_over, evaluation_score
        else:
            return fen, None, False, None
    except Exception as e:
        print(f"Invalid move: {e}")
        return fen, None, False, None

def get_position_evaluation(fen):
    """Get Stockfish evaluation for a chess position"""
    board = chess.Board(fen)
    engine = get_stockfish_engine()
    if not engine:
        return {'score': None, 'mate': None, 'evaluation_text': 'Engine unavailable'}

    try:
        info = engine.analyse(board, chess.engine.Limit(depth=15))
        score_obj = info["score"].white()
        
        if score_obj.is_mate():
            mate_in = score_obj.mate()
            text = f"Mate in {abs(mate_in)} for {'White' if mate_in > 0 else 'Black'}"
            return {'score': None, 'mate': mate_in, 'evaluation_text': text}
        else:
            centipawns = score_obj.score()
            return {'score': centipawns, 'mate': None, 'evaluation_text': format_evaluation(centipawns)}
    except Exception as e:
        print(f"Evaluation error: {e}")
        return {'score': None, 'mate': None, 'evaluation_text': 'Evaluation failed'}

def format_evaluation(centipawns):
    """Convert centipawn evaluation to human-readable text"""
    if centipawns is None: return "Unknown"
    pawns = centipawns / 100
    if pawns > 3: return f"White is winning (+{pawns:.1f})"
    elif pawns < -3: return f"Black is winning ({pawns:.1f})"
    elif pawns > 0.5: return f"White is slightly better (+{pawns:.1f})"
    elif pawns < -0.5: return f"Black is slightly better ({pawns:.1f})"
    else: return f"Equal ({pawns:+.1f})"

def calculate_won_games(user_id, user_email):
    """Calculate number of games won by user"""
    threads = Thread.query.filter_by(user_id=user_id).all()
    won_count = 0
    for thread in threads:
        if thread.game_result:
            first_msg = Message.query.filter_by(thread_id=thread.id).order_by(Message.date.asc()).first()
            if first_msg:
                user_is_white = (first_msg.sender == user_email)
                if user_is_white and thread.game_result == '1-0':
                    won_count += 1
                elif not user_is_white and thread.game_result == '0-1':
                    won_count += 1
    return won_count

def update_thread_fen(thread_id, fen):
    """Update the FEN for a thread"""
    thread = Thread.query.get(thread_id)
    if thread:
        thread.fen = fen
        db.session.commit()
        return True
    return False