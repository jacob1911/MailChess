import chess
from models import db, Thread


def get_or_create_fen(thread_id):
    """Get existing FEN from thread or initialize new board"""
    thread = Thread.query.get(thread_id)

    if not thread:
        return None

    if thread.fen:
        return thread.fen
    else:
        # Initialize new board
        board = chess.Board()
        thread.fen = board.fen()
        db.session.commit()
        return thread.fen


def process_move(fen, move_uci):
    """Process a chess move and return new FEN, or None if invalid"""
    board = chess.Board(fen)

    if not move_uci:
        return fen, None, False

    try:
        move = board.parse_uci(move_uci)
        if move in board.legal_moves:
            board.push(move)
            new_fen = board.fen()
            game_over = board.is_game_over()
            result = board.result() if game_over else None
            return new_fen, result, game_over
        else:
            return fen, None, False
    except Exception as e:
        print(f"Invalid move: {e}")
        return fen, None, False


def update_thread_fen(thread_id, fen):
    """Update the FEN for a thread"""
    thread = Thread.query.get(thread_id)
    if thread:
        thread.fen = fen
        db.session.commit()
        return True
    return False
