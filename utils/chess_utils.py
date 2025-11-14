import chess
import chess.engine
from models import db, Thread, Message

# Global Stockfish engine instance (reused across requests for performance)
_stockfish_engine = None

def get_stockfish_engine():
    """
    Get or create global Stockfish engine instance.

    Reuses the same engine instance for performance instead of creating
    a new one for each move.

    Returns:
        chess.engine.SimpleEngine: Stockfish engine instance
    """
    global _stockfish_engine

    if _stockfish_engine is None:
        try:
            _stockfish_engine = chess.engine.SimpleEngine.popen_uci(
                r".\stockfish\stockfish-windows-x86-64-avx2.exe"
            )
        except Exception as e:
            print(f"Failed to initialize Stockfish: {e}")
            return None

    return _stockfish_engine


def get_or_create_fen(thread_id):
    """
    Get existing FEN from thread or initialize new board.

    Args:
        thread_id (int): Database ID of the thread

    Returns:
        str: FEN string representing board position
    """
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
    """
    Process a chess move and return new FEN with Stockfish evaluation.

    Args:
        fen (str): Current position in FEN notation
        move_uci (str): Move in UCI format (e.g., "e2e4")

    Returns:
        tuple: (new_fen, result, game_over, evaluation_score)
            - new_fen (str): Updated FEN position
            - result (str): Game result ('1-0', '0-1', '1/2-1/2') or None
            - game_over (bool): Whether game has ended
            - evaluation_score (int): Centipawn evaluation from white's perspective

    Dependencies:
        - chess: For move validation
        - Stockfish: For position evaluation
    """
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

            # Get Stockfish evaluation
            evaluation_score = None
            engine = get_stockfish_engine()
            if engine:
                try:
                    info = engine.analyse(board, chess.engine.Limit(depth=15))
                    score_obj = info["score"].white()

                    # Convert to centipawns (None if mate)
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
    """
    Get Stockfish evaluation for a chess position.

    Args:
        fen (str): Position in FEN notation

    Returns:
        dict: {
            'score': int or None (centipawns from white's perspective),
            'mate': int or None (mate in X moves),
            'evaluation_text': str (human-readable evaluation)
        }

    Dependencies:
        - Stockfish engine
    """
    board = chess.Board(fen)
    engine = get_stockfish_engine()

    if not engine:
        return {
            'score': None,
            'mate': None,
            'evaluation_text': 'Engine unavailable'
        }

    try:
        info = engine.analyse(board, chess.engine.Limit(depth=15))
        score_obj = info["score"].white()

        if score_obj.is_mate():
            mate_in = score_obj.mate()
            return {
                'score': None,
                'mate': mate_in,
                'evaluation_text': f"Mate in {abs(mate_in)} for {'White' if mate_in > 0 else 'Black'}"
            }
        else:
            centipawns = score_obj.score()
            return {
                'score': centipawns,
                'mate': None,
                'evaluation_text': format_evaluation(centipawns)
            }
    except Exception as e:
        print(f"Evaluation error: {e}")
        return {
            'score': None,
            'mate': None,
            'evaluation_text': 'Evaluation failed'
        }


def format_evaluation(centipawns):
    """
    Convert centipawn evaluation to human-readable text.

    Args:
        centipawns (int): Evaluation in centipawns from white's perspective

    Returns:
        str: Human-readable evaluation (e.g., "White is winning (+3.5)")
    """
    if centipawns is None:
        return "Unknown"

    pawns = centipawns / 100

    if pawns > 3:
        return f"White is winning (+{pawns:.1f})"
    elif pawns < -3:
        return f"Black is winning ({pawns:.1f})"
    elif pawns > 0.5:
        return f"White is slightly better (+{pawns:.1f})"
    elif pawns < -0.5:
        return f"Black is slightly better ({pawns:.1f})"
    else:
        return f"Equal ({pawns:+.1f})"


def calculate_won_games(user_id, user_email):
    """
    Calculate number of games won by user.

    Determines if user was white or black based on first message sender,
    then checks game_result to see if they won.

    Args:
        user_id (int): Database ID of the user
        user_email (str): User's email address

    Returns:
        int: Number of games won by user

    Dependencies:
        - Models: Thread, Message
    """
    threads = Thread.query.filter_by(user_id=user_id).all()

    won_count = 0
    for thread in threads:
        if thread.game_result:
            # Determine if user is white or black from first message
            first_msg = Message.query.filter_by(thread_id=thread.id).order_by(Message.date.asc()).first()
            if first_msg:
                # User who sent first message is white
                user_is_white = (first_msg.sender == user_email)

                if user_is_white and thread.game_result == '1-0':
                    won_count += 1
                elif not user_is_white and thread.game_result == '0-1':
                    won_count += 1

    return won_count


def update_thread_fen(thread_id, fen):
    """
    Update the FEN for a thread.

    Args:
        thread_id (int): Database ID of the thread
        fen (str): New FEN position

    Returns:
        bool: True if update succeeded, False otherwise
    """
    thread = Thread.query.get(thread_id)
    if thread:
        thread.fen = fen
        db.session.commit()
        return True
    return False
