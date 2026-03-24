from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from decimal import Decimal
import os
from dotenv import load_dotenv
#from extra_endpoints import *


app = Flask(__name__)
CORS(app,origins=["http://localhost:5173","https://odi-da.netlify.app"])

load_dotenv()
# Database connection parameters
db_params = {
    "host": os.getenv("DB_HOST"),
    "database": os.getenv("DB_DATABASE"),
    "user": os.getenv("DB_USERNAME"),
    "password": os.getenv("DB_PASSWORD"),
    "port": os.getenv("DB_PORT"),
    "sslmode": "require"
}

# Database connection function
def get_db_connection():
    conn=psycopg2.connect(**db_params)
    conn.autocommit=True
    return conn


# 1. Teams API
@app.route('/api/teams')
def get_teams():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT DISTINCT team_bat FROM odi_db AS teams ")
    teams = [row['team_bat'] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(teams)

# 2. Players API
@app.route('/api/players')
def get_players():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT DISTINCT player FROM (SELECT bat AS player FROM odi_db UNION SELECT bowl AS player FROM odi_db) AS players ORDER BY player")
    players = [row['player'] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(players)

# 3. Matches API
@app.route('/api/matches')
def get_matches():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT DISTINCT p_match, team_bat || ' vs ' || team_bowl AS teams, date FROM odi_db ORDER BY date DESC LIMIT 100")
    matches = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(matches)

# 4. Seasons API
@app.route('/api/seasons')
def get_seasons():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT DISTINCT year FROM odi_db ORDER BY year DESC")
    seasons = [row['year'] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(seasons)

# 5. Team Performance API
@app.route('/api/team-performance')
def get_team_performance():
    team = request.args.get('team')
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT 
            COUNT(*) FILTER (WHERE winner = %s) AS wins,
            COUNT(*) FILTER (WHERE winner != %s AND winner != 'No Result') AS losses,
            COUNT(*) FILTER (WHERE winner = 'No Result') AS ties
        FROM (
            SELECT DISTINCT p_match, winner
            FROM odi_db
            WHERE team_bat = %s OR team_bowl = %s
        ) AS team_matches
    """, (team, team, team, team))
    performance = cur.fetchone()
    cur.close()
    conn.close()
    return jsonify(performance)

# 6. Player Stats API
@app.route('/api/player-stats')
def get_player_stats():
    player = request.args.get('player')
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Batting stats
    cur.execute("""
            SELECT 
                SUM(CAST(batruns AS INTEGER)) AS total_runs,
                SUM(CAST(ballfaced AS INTEGER)) AS balls_faced,
                ROUND(
                    CASE
                        WHEN SUM(CAST(ballfaced AS FLOAT)) = 0 THEN 0
                        ELSE CAST(SUM(CAST(batruns AS FLOAT)) / SUM(CAST(ballfaced AS FLOAT)) * 100 AS NUMERIC)
                    END, 2
                ) AS strike_rate,
                ROUND(
                CAST(
                    CASE 
                    WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                    ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                    END AS NUMERIC
                ), 2
                ) AS average
                FROM odi_db
                WHERE bat = %s
    """, (player,))
    batting_stats = cur.fetchone()
    
    # Bowling stats
    cur.execute("""
        SELECT 
            SUM(CAST(bowlruns AS INTEGER)) AS runs_conceded,
            COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END) AS wickets,
            ROUND(CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(*) / 6.0, 0) AS NUMERIC), 2) AS economy_rate,
            ROUND(CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END), 0) AS NUMERIC), 2) AS average,
            ROUND(CAST(CAST(COUNT(*) AS FLOAT) / NULLIF(COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END), 0) AS NUMERIC), 2) AS strike_rate
        FROM odi_db
        WHERE bowl = %s;

    """, (player,))
    bowling_stats = cur.fetchone()

    # Bat Hand
    cur.execute("""
        SELECT 
            bat_hand
            FROM odi_db
        WHERE bat = %s;

    """, (player,))
    bat_hand = cur.fetchone()

    cur.close()
    conn.close()
    return jsonify({"batting": batting_stats, "bowling": bowling_stats,"bat_hand":bat_hand})

# 7. Match Summary API
@app.route('/api/match-summary')
def get_match_summary():
    match_id = request.args.get('match_id')
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT 
            p_match,
            team_bat,
            team_bowl,
            SUM(CAST(score AS INTEGER)) AS total_runs,
            COUNT(CASE WHEN outcome = 'out' THEN 1 END) AS wickets,
            date,
            ground,
            winner
        FROM odi_db
        WHERE p_match = %s
        GROUP BY p_match, team_bat, team_bowl, date, ground, winner
        ORDER BY p_match, team_bat
    """, (match_id,))
    innings = cur.fetchall()
    
    cur.execute("""
        SELECT 
            bat AS player,
            SUM(CAST(batruns AS INTEGER)) AS runs,
            COUNT(CASE WHEN outcome = 'out' THEN 1 END) AS wickets,
            CASE 
                WHEN SUM(CAST(batruns AS INTEGER)) >= 50 THEN 'Fifty'
                WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) >= 3 THEN 'Three-fer'
                ELSE 'Notable performance'
            END AS achievement
        FROM odi_db
        WHERE p_match = %s
        GROUP BY bat
        HAVING SUM(CAST(batruns AS INTEGER)) >= 50 OR COUNT(CASE WHEN outcome = 'out' THEN 1 END) >= 3
        ORDER BY SUM(CAST(batruns AS INTEGER)) DESC, COUNT(CASE WHEN outcome = 'out' THEN 1 END) DESC
        LIMIT 5
    """, (match_id,))
    key_performances = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return jsonify({
        "innings": innings,
        "key_performances": key_performances
    })

# 8. Season Overview API
@app.route('/api/season-overview')
def get_season_overview():
    year = request.args.get('year')
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Team performance
    cur.execute("""
        SELECT 
            team,
            COUNT(*) FILTER (WHERE winner = team) AS wins
        FROM (
            SELECT DISTINCT p_match, team_bat AS team, winner
            FROM odi_db
            WHERE year = %s
            UNION
            SELECT DISTINCT p_match, team_bowl AS team, winner
            FROM odi_db
            WHERE year = %s
        ) AS team_matches
        GROUP BY team
        ORDER BY wins DESC
        LIMIT 10
    """, (year, year))
    team_performance = cur.fetchall()
    
    # Top scorers
    cur.execute("""
        SELECT 
            bat AS name,
            SUM(CAST(batruns AS INTEGER)) AS runs
            FROM odi_db
            WHERE year = %s
            GROUP BY bat
            ORDER BY runs DESC
            LIMIT 5
    """, (year,))
    top_scorers = cur.fetchall()

    # Top Wicket-takers
    cur.execute("""
        SELECT 
            bowl AS name,
            COUNT(CASE WHEN outcome = 'out' THEN 1 END) AS wickets
            FROM odi_db
            WHERE year = %s
            GROUP BY bowl
            ORDER BY COUNT(CASE WHEN outcome = 'out' THEN 1 END) DESC
            LIMIT 5
    """, (year,))
    top_bowlers = cur.fetchall()
    
    # Season highlights (this is a placeholder - you might want to store this data separately)
    highlights = [
        f"Most runs: {top_scorers[0]['name']} ({top_scorers[0]['runs']} runs)",
        f"Most wickets: {top_bowlers[0]['name']} ({top_bowlers[0]['wickets']} wickets)",
        f"Most wins: {team_performance[0]['team']} ({team_performance[0]['wins']} wins)"
    ]
    
    cur.close()
    conn.close()
    
    return jsonify({
        "team_performance": team_performance,
        "top_scorers": top_scorers,
        "top_bowlers": top_bowlers,
        "highlights": highlights
    })

    # Add this new endpoint
@app.route('/api/team-season-performance')
def get_team_season_performance():
    team = request.args.get('team')
    if not team:
        return jsonify({"error": "Team parameter is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        WITH team_matches AS (
            SELECT DISTINCT p_match, year, winner,
                CASE 
                    WHEN team_bat = %s THEN team_bat
                    WHEN team_bowl = %s THEN team_bowl
                END AS team
            FROM odi_db
            WHERE team_bat = %s OR team_bowl = %s
        )
        SELECT 
            year,
            COUNT(*) AS total_matches,
            COUNT(*) FILTER (WHERE winner = %s) AS wins,
            COUNT(*) FILTER (WHERE winner != %s AND winner != 'No Result') AS losses,
            COUNT(*) FILTER (WHERE winner = 'No Result') AS ties
        FROM team_matches
        GROUP BY year
        ORDER BY year
    """, (team, team, team, team, team, team))

    seasons = cur.fetchall()

    # Calculate win percentage and add it to each season's data
    for season in seasons:
        total_decided = season['total_matches'] - season['ties']
        season['win_percentage'] = round((season['wins'] / total_decided * 100), 2) if total_decided > 0 else 0

    cur.close()
    conn.close()
    return jsonify(seasons)


    # Add this new endpoint to your Flask application

@app.route('/api/player-matchup')
def get_player_matchup():
    batsman = request.args.get('batsman')
    bowler = request.args.get('bowler')
    
    if not batsman or not bowler:
        return jsonify({"error": "Both batsman and bowler parameters are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT 
            COUNT(*) AS balls_faced,
            SUM(CAST(batruns AS INTEGER)) AS runs_scored,
            SUM(CASE WHEN outcome = 'out' THEN 1 ELSE 0 END) AS dismissals,
            ROUND(CAST(SUM(CAST(batruns AS FLOAT)) / NULLIF(COUNT(*), 0) * 100 AS NUMERIC), 2) AS strike_rate,
            ROUND(
            CAST(
                CASE 
                WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                END AS NUMERIC
            ), 2
            ) AS average,
            ROUND(CAST(SUM(CAST(batruns AS FLOAT)) / NULLIF(COUNT(*) / 6, 0) AS NUMERIC), 2) AS economy_rate
        FROM odi_db
        WHERE bat = %s AND bowl = %s
    """, (batsman, bowler))

    matchup = cur.fetchone()

    cur.close()
    conn.close()

    return jsonify(matchup)

    # 6. Scat
@app.route('/api/batscatter')
def get_batscatter_stats():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Batting Scatterplot
    cur.execute("""
        SELECT 
            bat AS batsman,
            ROUND(
                CASE
                    WHEN SUM(CAST(ballfaced AS FLOAT)) = 0 THEN 0
                    ELSE CAST(SUM(CAST(batruns AS FLOAT)) / SUM(CAST(ballfaced AS FLOAT)) * 100 AS NUMERIC)
                END, 2
            ) AS strike_rate,
            ROUND(
                CAST(
                    CASE 
                        WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                        ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                    END AS NUMERIC
                ), 2
            ) AS average
        FROM odi_db
        GROUP BY bat
        HAVING COUNT(DISTINCT p_match) > 25
        ORDER BY batsman;
    """)
    bat_stats = cur.fetchall()
    
    cur.close()
    conn.close()
    return jsonify(bat_stats)

@app.route('/api/bowlscatter')
def get_bowlscatter_stats():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Bowling Scatterplot
    cur.execute("""
        SELECT 
            bowl AS bowler,
            ROUND(CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(*) / 6.0, 0) AS NUMERIC), 2) AS economy,
            ROUND(CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END), 0) AS NUMERIC), 2) AS average
        FROM odi_db
        GROUP BY bowl
        HAVING COUNT(DISTINCT p_match) > 25 
    """)
    bowl_stats = cur.fetchall()
    
    cur.close()
    conn.close()
    return jsonify(bowl_stats)

    # 6. Player Stats API
@app.route('/api/player-performance')
def get_player_statsbyyear():
    player = request.args.get('player')
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Batting stats
    cur.execute("""
            SELECT 
                year,
                SUM(CAST(batruns as INTEGER)) as runs,
                ROUND(
                    CASE
                        WHEN SUM(CAST(ballfaced AS FLOAT)) = 0 THEN 0
                        ELSE CAST(SUM(CAST(batruns AS FLOAT)) / SUM(CAST(ballfaced AS FLOAT)) * 100 AS NUMERIC)
                    END, 2
                ) AS strike_rate,
                ROUND(
                CAST(
                    CASE 
                    WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                    ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                    END AS NUMERIC
                ), 2
                ) AS average
            FROM odi_db
            WHERE bat = %s
            GROUP BY year
            ORDER BY year
    """, (player,))
    stats = cur.fetchall()
    
    cur.close()
    conn.close()
    return jsonify(stats)



@app.route('/api/team-contributions')
def get_player_contri():
    # Extract the team and year from the request arguments
    team = request.args.get('team', 'India')  # default to 'India' if not provided
    year = request.args.get('year', '2016')   # default to '2018' if not provided

    # Connect to the database
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Batting stats query
    cur.execute("""
        SELECT 
            bat AS player_name,
            SUM(CAST(batruns AS INTEGER)) AS runs
        FROM odi_db
        WHERE team_bat = %s AND year = %s
        GROUP BY bat
    """, (team, year))
    bat_stats = cur.fetchall()

    # Bowling stats query
    cur.execute("""
        SELECT 
            bowl AS player_name,
            COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END) AS wickets
        FROM odi_db
        WHERE team_bowl = %s AND year = %s
        GROUP BY bowl
    """, (team, year))
    bowl_stats = cur.fetchall()
    
    # Combine batting and bowling stats
    player_contributions = {}

    for bat_stat in bat_stats:
        player_name = bat_stat['player_name']
        if player_name not in player_contributions:
            player_contributions[player_name] = {'name': player_name, 'runs': 0, 'wickets': 0}
        player_contributions[player_name]['runs'] = bat_stat['runs']

    for bowl_stat in bowl_stats:
        player_name = bowl_stat['player_name']
        if player_name not in player_contributions:
            player_contributions[player_name] = {'name': player_name, 'runs': 0, 'wickets': 0}
        player_contributions[player_name]['wickets'] = bowl_stat['wickets']
    
    # Close the cursor and connection
    cur.close()
    conn.close()

    # Convert the player contributions to a list
    contributions_list = list(player_contributions.values())

    # Return the data in the specified format
    return jsonify(contributions_list)


@app.route('/api/player-run-distribution')
def get_player_run_distribution():
    player = request.args.get('player')
    
    if not player:
        return jsonify({'error': 'Please provide a player name'}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Query to get player's run distribution, seasons, and opponents
    run_distribution_query = """
        SELECT 
            SUM(CAST(batruns AS INTEGER)) AS runs,
            team_bowl AS opponent
        FROM odi_db
        WHERE bat = %s
        GROUP BY p_match, team_bowl
        ORDER BY p_match, team_bowl
    """
    cur.execute(run_distribution_query)
    innings_data = cur.fetchall()

    # Extract unique seasons and opponents
    #seasons = sorted(set([row['season'] for row in distribution_data]))
    #opponents = sorted(set([row['opponent'] for row in distribution_data]))

    cur.close()
    conn.close()

    # Format the response
    response = {
        'distribution': [
            {'runs': row['runs'], 'opponent': row['opponent']}
            for row in innings_data
        ]
    }

    return jsonify(response)

@app.route('/api/player-role-analysis')
def get_player_role_analysis():
    player = request.args.get('player')
    
    if not player:
       return jsonify({'error': 'Please provide a player name'}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT 
            CASE 
                WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
                WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle Overs'
                ELSE 'Death Overs'
            END AS role,
            SUM(CAST(batruns AS INTEGER)) AS runs,
            ROUND(
                    CASE
                        WHEN SUM(CAST(ballfaced AS FLOAT)) = 0 THEN 0
                        ELSE CAST(SUM(CAST(batruns AS FLOAT)) / SUM(CAST(ballfaced AS FLOAT)) * 100 AS NUMERIC)
                    END, 2
                ) AS strike_rate,
                ROUND(
                CAST(
                    CASE 
                    WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                    ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                    END AS NUMERIC
                ), 2
                ) AS average
        FROM odi_db
        WHERE bat = %s
        GROUP BY role
    """, (player,))

    batting_data = cur.fetchall()

    # Query to get bowling role analysis with type casting
    cur.execute("""
        SELECT 
            CASE 
                WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
                WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle Overs'
                ELSE 'Death Overs'
            END AS role,
            COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END) AS wickets,
            ROUND(CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(*) / 6.0, 0) AS NUMERIC), 2) AS economy_rate,
            ROUND(CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END), 0) AS NUMERIC), 2) AS average,
            ROUND(CAST(CAST(COUNT(*) AS FLOAT) / NULLIF(COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END), 0) AS NUMERIC), 2) AS strike_rate
        FROM odi_db
        WHERE bowl = %s
        GROUP BY role
    """, (player,))

    bowling_data = cur.fetchall()

    cur.close()
    conn.close()

    # Format the response
    response = {
        'batting': batting_data,
        'bowling': bowling_data
    }

    return jsonify(response)

@app.route('/api/player-typeagainst-analysis')
def get_player_typeagainst_analysis():
    player = request.args.get('player')
    
    if not player:
       return jsonify({'error': 'Please provide a player name'}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT 
            bowl_style as type,
            SUM(CAST(batruns AS INTEGER)) AS runs,
            ROUND(
                    CASE
                        WHEN SUM(CAST(ballfaced AS FLOAT)) = 0 THEN 0
                        ELSE CAST(SUM(CAST(batruns AS FLOAT)) / SUM(CAST(ballfaced AS FLOAT)) * 100 AS NUMERIC)
                    END, 2
                ) AS strike_rate,
                ROUND(
                CAST(
                    CASE 
                    WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                    ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                    END AS NUMERIC
                ), 2
                ) AS average
        FROM odi_db
        WHERE bat = %s
        GROUP BY bowl_style
        ORDER BY bowl_style
    """, (player,))

    batting_data = cur.fetchall()


    cur.execute("""
        SELECT 
            bat_hand as type,
            COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END) AS wickets,
            ROUND(CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(*) / 6.0, 0) AS NUMERIC), 2) AS economy_rate,
            ROUND(CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END), 0) AS NUMERIC), 2) AS average,
            ROUND(CAST(CAST(COUNT(*) AS FLOAT) / NULLIF(COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END), 0) AS NUMERIC), 2) AS strike_rate
        FROM odi_db
        WHERE bowl = %s
        GROUP BY bat_hand
        ORDER BY bat_hand
    """, (player,))
    bowling_data = cur.fetchall()

    cur.close()
    conn.close()

    response = {
        'batting': batting_data,
        'bowling': bowling_data
    }

    return jsonify(response)

@app.route('/api/batter-line-length')
def get_batter_line_length():
    player = request.args.get('player')
    if not player:
        return jsonify({"error": "Player parameter is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT 
            line,
            length,
            SUM(CAST(batruns AS INTEGER)) AS total_runs,
            COUNT(*) AS balls_faced
        FROM odi_db
        WHERE bat = %s
        GROUP BY line, length
        ORDER BY total_runs DESC
    """, (player,))

    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(data)


# ====================================
# 2️⃣ Batter Line-Length Strike Rate
# ====================================
@app.route('/api/batter-line-length-sr')
def get_batter_line_length_sr():
    player = request.args.get('player')
    if not player:
        return jsonify({"error": "Player parameter is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT 
            line,
            length,
            SUM(CAST(batruns AS INTEGER)) AS total_runs,
            COUNT(*) AS balls_faced,
            ROUND(
                CASE 
                    WHEN COUNT(*) = 0 THEN 0
                    ELSE CAST(SUM(CAST(batruns AS FLOAT)) / COUNT(*) * 100 AS NUMERIC)
                END, 2
            ) AS strike_rate,
            ROUND(SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS dot_pct,
            ROUND(SUM(CASE WHEN outcome IN ('four', 'six') THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS boundary_pct,
            ROUND(
                    CASE WHEN COUNT(control) > 0 
                        THEN (
                            SUM(
                                COALESCE(
                                    NULLIF(
                                        NULLIF(LOWER(control), 'nan'),
                                        ''
                                    )::NUMERIC,
                                    0
                                )
                            ) / COUNT(control) * 100
                        )
                        ELSE 0 END, 2
                ) AS control_pct
        FROM odi_db
        WHERE bat = %s
        GROUP BY line, length
    """, (player,))

    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(data)

@app.route("/api/batter-line-length-sr2")
def batter_line_length_sr2():
    player = request.args.get("player")
    if not player:
        return jsonify({"error": "Missing player"}), 400

    where_clause = "WHERE bat = %s"
    params = [player]

    bowl_kind = request.args.get("bowl_kind")
    if bowl_kind:
        where_clause += " AND bowl_kind ILIKE %s"
        params.append(bowl_kind)

    bowl_style = request.args.get("bowl_style")
    if bowl_style:
        where_clause += " AND bowl_style ILIKE %s"
        params.append(bowl_style)

    phase = request.args.get("phase")  # optional (Powerplay / Middle Overs / Death Overs)
    if phase:
        where_clause += """ AND (
            CASE 
                WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
                WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle Overs'
                ELSE 'Death Overs'
            END
        ) ILIKE %s"""
        params.append(phase)

    bowler = request.args.get("bowler")  # optional
    if bowler:
        where_clause += " AND bowl ILIKE %s"
        params.append(bowler)

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    #  Common SELECT fields
    select_fields = """
        line, 
        length,
        SUM(CAST(batruns AS FLOAT)) AS total_runs,
        COUNT(*) AS balls_faced,
        ROUND(
            CASE 
                WHEN COUNT(*) = 0 THEN 0
                ELSE CAST(SUM(CAST(batruns AS FLOAT)) / COUNT(*) * 100 AS NUMERIC)
            END, 2
        ) AS strike_rate,
        ROUND(SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS dot_pct,
        ROUND(SUM(CASE WHEN outcome IN ('four','six') THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS boundary_pct,
        ROUND(
            CASE WHEN COUNT(control) > 0 
                THEN (
                    SUM(
                        COALESCE(
                            NULLIF(
                                NULLIF(LOWER(control), 'nan'),
                                ''
                            )::NUMERIC,
                            0
                        )
                    ) / COUNT(control) * 100
                )
                ELSE 0 END, 2
        ) AS control_pct
    """

    # ✅ If phase-based breakdown is needed (like for matchup/phase components)
    if phase:
        query = f"""
            SELECT 
                {select_fields},
                CASE 
                    WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
                    WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle Overs'
                    ELSE 'Death Overs'
                END AS phase
            FROM odi_db
            {where_clause}
            GROUP BY line, length, phase
            ORDER BY line, length;
        """
    else:
        # ✅ Global aggregation — no phase grouping
        query = f"""
            SELECT 
                {select_fields}
            FROM odi_db
            {where_clause}
            GROUP BY line, length
            ORDER BY line, length;
        """

    cur.execute(query, tuple(params))
    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(data)




# ===============================
# 3️⃣ Batter Shot Type Analysis
# ===============================
@app.route('/api/batter-shot-types', methods=['GET'])
def get_batter_shot_types():
    try:
        player = request.args.get('player')
        if not player:
            return jsonify({"error": "Missing 'player' parameter"}), 400
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # --- Fetch and cast numeric columns ---
        query = """
            SELECT 
                shot,
                SUM(CAST(batruns AS NUMERIC)) AS total_runs,
                SUM(CAST(ballfaced AS NUMERIC)) AS total_balls,
                SUM(CASE WHEN CAST("out" AS BOOLEAN) = TRUE THEN 1 ELSE 0 END) AS total_outs,
                SUM(
                COALESCE(
                    NULLIF(NULLIF(LOWER(control), 'nan'), '')::NUMERIC, 
                    0
                )
                ) AS control_sum,
                COUNT(control) AS control_count,
                ROUND(
                    CASE
                        WHEN SUM(CAST(ballfaced AS FLOAT)) = 0 THEN 0
                        ELSE CAST(SUM(CAST(batruns AS FLOAT)) / SUM(CAST(ballfaced AS FLOAT)) * 100 AS NUMERIC)
                    END, 2
                ) AS strike_rate,
                ROUND(
                CAST(
                    CASE 
                    WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                    ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                    END AS NUMERIC
                ), 2
                ) AS average,
                 ROUND(
                    CASE WHEN COUNT(control) > 0 
                        THEN (
                            SUM(
                                COALESCE(
                                    NULLIF(
                                        NULLIF(LOWER(control), 'nan'),
                                        ''
                                    )::NUMERIC,
                                    0
                                )
                            ) / COUNT(control) * 100
                        )
                        ELSE 0 END, 2
                ) AS control_pct
            FROM odi_db
            WHERE bat = %s
            GROUP BY shot
            ORDER BY total_runs DESC;
        """
        cur.execute(query, (player,))
        results = cur.fetchall()

        
        return jsonify(results)

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 500




# ===============================
# 4️⃣ Bowler Line-Length Analysis
# ===============================
@app.route('/api/bowler-line-length')
def get_bowler_line_length():
    player = request.args.get('player')
    if not player:
        return jsonify({"error": "Player parameter is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT 
            line,
            length,
            COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END) AS wickets,
            SUM(CAST(bowlruns AS INTEGER)) AS runs_conceded,
            ROUND(
                CASE 
                    WHEN COUNT(*) = 0 THEN 0
                    ELSE CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(*) / 6.0, 0) AS NUMERIC)
                END, 2
            ) AS economy,
            ROUND(SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS dot_pct,
            ROUND(SUM(CASE WHEN outcome IN ('four', 'six') THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS boundary_pct,
            ROUND(
                    CASE WHEN COUNT(control) > 0 
                        THEN (
                            SUM(
                                COALESCE(
                                    NULLIF(
                                        NULLIF(LOWER(control), 'nan'),
                                        ''
                                    )::NUMERIC,
                                    0
                                )
                            ) / COUNT(control) * 100
                        )
                        ELSE 0 END, 2
                ) AS control_pct
        FROM odi_db
        WHERE bowl = %s
        GROUP BY line, length
        ORDER BY wickets DESC, economy ASC
    """, (player,))

    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(data)


# =================================
# 5️⃣ Extended Batting Stats
# =================================
@app.route('/api/batting-stats-extended')
def get_batting_stats_extended():
    player = request.args.get('player')
    if not player:
        return jsonify({"error": "Player parameter is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT 
            team_bowl AS opponent,
            SUM(CAST(batruns AS INTEGER)) AS total_runs,
            COUNT(CASE WHEN outcome = 'out' THEN 1 END) AS dismissals,
            ROUND(
                CASE 
                    WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                    ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                END, 2
            ) AS average,
            ROUND(
                CASE 
                    WHEN SUM(CAST(ballfaced AS FLOAT)) = 0 THEN 0
                    ELSE SUM(CAST(batruns AS FLOAT)) / SUM(CAST(ballfaced AS FLOAT)) * 100
                END, 2
            ) AS strike_rate
        FROM odi_db
        WHERE bat = %s
        GROUP BY team_bowl
        ORDER BY total_runs DESC
    """, (player,))

    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(data)


# =================================
# 6️⃣ Extended Bowling Stats
# =================================
@app.route('/api/bowling-stats-extended')
def get_bowling_stats_extended():
    player = request.args.get('player')
    if not player:
        return jsonify({"error": "Player parameter is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT 
            team_bat AS opponent,
            COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END) AS wickets,
            SUM(CAST(bowlruns AS INTEGER)) AS runs_conceded,
            ROUND(
                CASE 
                    WHEN COUNT(*) = 0 THEN 0
                    ELSE CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(*) / 6.0, 0) AS NUMERIC)
                END, 2
            ) AS economy,
            ROUND(
                CASE 
                    WHEN COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END) = 0 THEN 0
                    ELSE SUM(CAST(bowlruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END)
                END, 2
            ) AS bowling_average
        FROM odi_db
        WHERE bowl = %s
        GROUP BY team_bat
        ORDER BY wickets DESC
    """, (player,))

    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(data)

@app.route('/api/batter-bowl-types', methods=['GET'])
def get_batter_bowl_types():
    try:
        player = request.args.get('player')
        if not player:
            return jsonify({"error": "Missing 'player' parameter"}), 400
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # --- Fetch and cast numeric columns ---
        query = """
            SELECT 
                bowl_style,
                COUNT(*) AS total_balls,
                SUM(CAST(batruns AS NUMERIC)) AS total_runs,
                SUM(CASE WHEN CAST("out" AS BOOLEAN) = TRUE THEN 1 ELSE 0 END) AS total_outs,
                SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END) AS dots,
                ROUND(
                CASE
                    WHEN SUM(CAST(ballfaced AS FLOAT)) = 0 THEN 0
                    ELSE CAST(SUM(CAST(batruns AS FLOAT)) / SUM(CAST(ballfaced AS FLOAT)) * 100 AS NUMERIC)
                END, 2
            ) 	AS strike_rate,
                ROUND(
                CAST(
                    CASE 
                    WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                    ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                    END AS NUMERIC
                ), 2
                ) AS average,
                ROUND(SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS dot_pct,
                ROUND(SUM(CASE WHEN outcome IN ('four', 'six') THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS boundary_pct

            FROM odi_db
            WHERE bat = %s
            GROUP BY bowl_style
            ORDER BY total_runs DESC;

        """
        cur.execute(query, (player,))
        results = cur.fetchall()

        
        return jsonify(results)

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/batter-bowl-phase-types', methods=['GET'])
def get_batter_bowl_phase_types():
    try:
        player = request.args.get('player')
        if not player:
            return jsonify({"error": "Missing 'player' parameter"}), 400
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # --- Fetch and cast numeric columns ---
        query = """
            SELECT
                CASE 
                WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
                WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle Overs'
                ELSE 'Death Overs'
                END AS phase,
                bowl_style,
                COUNT(*) AS total_balls,
                SUM(CAST(batruns AS NUMERIC)) AS total_runs,
                SUM(CASE WHEN CAST("out" AS BOOLEAN) = TRUE THEN 1 ELSE 0 END) AS total_outs,
                SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END) AS dots,
                ROUND(
                CASE
                    WHEN SUM(CAST(ballfaced AS FLOAT)) = 0 THEN 0
                    ELSE CAST(SUM(CAST(batruns AS FLOAT)) / SUM(CAST(ballfaced AS FLOAT)) * 100 AS NUMERIC)
                END, 2
            ) 	AS strike_rate,
                ROUND(
                CAST(
                    CASE 
                    WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                    ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                    END AS NUMERIC
                ), 2
                ) AS average,
                ROUND(SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS dot_pct,
                ROUND(SUM(CASE WHEN outcome IN ('four', 'six') THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS boundary_pct

            FROM odi_db
            WHERE bat = %s
            GROUP BY bowl_style,phase
            ORDER BY total_runs DESC;

        """
        cur.execute(query, (player,))
        results = cur.fetchall()

        
        return jsonify(results)

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/api/batter-wagon")
def batter_wagon():
    player = request.args.get("player")
    if not player:
        return jsonify({"error": "Missing player"}), 400

    # --- Build dynamic WHERE clause ---
    where_clause = "WHERE bat = %s"
    params = [player]

    bowl_kind = request.args.get("bowl_kind")
    if bowl_kind:
        where_clause += " AND bowl_kind ILIKE %s"
        params.append(bowl_kind)

    bowl_style = request.args.get("bowl_style")
    if bowl_style:
        where_clause += " AND bowl_style ILIKE %s"
        params.append(bowl_style)

    bowler = request.args.get("bowler")
    if bowler:
        where_clause += " AND bowl ILIKE %s"
        params.append(bowler)

    phase = request.args.get("phase")
    if phase:
        where_clause += """ AND (
            CASE 
                WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
                WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle Overs'
                ELSE 'Death Overs'
            END
        ) ILIKE %s"""
        params.append(phase)

    # --- Query ---
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

     #  Common SELECT fields
    select_fields = """
            wagonZone,
            COUNT(*) AS balls_faced,
            SUM(CAST(batruns AS FLOAT)) AS total_runs,
            ROUND(
                CASE 
                    WHEN COUNT(*) = 0 THEN 0
                    ELSE CAST(SUM(CAST(batruns AS FLOAT)) / COUNT(*) * 100 AS NUMERIC)
                END, 2
            ) AS strike_rate,
            ROUND(SUM(CASE WHEN outcome IN ('four','six') THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS boundary_pct,
            ROUND(SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS dot_pct,
            ROUND(
                CASE WHEN COUNT(control) > 0 
                    THEN (
                        SUM(
                            COALESCE(
                                NULLIF(
                                    NULLIF(LOWER(control), 'nan'),
                                    ''
                                )::NUMERIC,
                                0
                            )
                        ) / COUNT(control) * 100
                    )
                    ELSE 0 END, 2
            ) AS control_pct
    """

    # ✅ If phase-based breakdown is needed (like for matchup/phase components)
    if phase and bowl_style:
        query = f"""
            SELECT 
                {select_fields},
                CASE 
                    WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
                    WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle Overs'
                    ELSE 'Death Overs'
                END AS phase,
                bowl_style
            FROM odi_db
            {where_clause}
            GROUP BY wagonZone, phase,bowl_style
            ORDER BY wagonZone;
        """
    else:
        # ✅ Global aggregation — no phase grouping
        query = f"""
            SELECT 
                {select_fields}
            FROM odi_db
            {where_clause}
            GROUP BY wagonZone
            ORDER BY wagonZone;
        """

    cur.execute(query, tuple(params))
    data = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify(data)



@app.route("/api/batter-skill-profile")
def player_skill_profile():
    player = request.args.get("player")
    if not player:
        return jsonify({"error": "Missing player"}), 400
    
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=RealDictCursor)

    query = f"""
        SELECT
            CASE 
            WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
            WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle Overs'
            ELSE 'Death Overs'
            END AS phase, 
            ROUND(
                CASE
                    WHEN SUM(CAST(ballfaced AS FLOAT)) = 0 THEN 0
                    ELSE CAST(SUM(CAST(batruns AS FLOAT)) / SUM(CAST(ballfaced AS FLOAT)) * 100 AS NUMERIC)
                END, 2
            ) AS strike_rate,
            ROUND(
            CAST(
                CASE 
                WHEN COUNT(CASE WHEN outcome = 'out' THEN 1 END) = 0 THEN SUM(CAST(batruns AS FLOAT))
                ELSE SUM(CAST(batruns AS FLOAT)) / COUNT(CASE WHEN outcome = 'out' THEN 1 END)
                END AS NUMERIC
            ), 2
            ) AS average
            FROM odi_db
            WHERE bat = %s
            GROUP BY phase
    """

    cur.execute(query, (player,))
    sr_data = cur.fetchall()

    query2 = f"""
        SELECT
            ROUND(
                (SUM(CASE WHEN POSITION('no run' IN LOWER(TRIM(outcome))) > 0 THEN 1 ELSE 0 END)::NUMERIC 
                / NULLIF(COUNT(*),0)) * 100, 2
            ) AS dot_pct,
            ROUND(
                (SUM(CASE WHEN LOWER(TRIM(outcome)) IN ('four', '6', 'six') THEN 1 ELSE 0 END)::NUMERIC 
                / NULLIF(COUNT(*),0)) * 100, 2
            ) AS boundary_pct,
            ROUND(
                CAST(
                    (
                        (
                            SUM(CAST(batruns AS NUMERIC))
                            - SUM(CASE WHEN outcome IN ('four', 'six') THEN CAST(batruns AS NUMERIC) ELSE 0 END)
                        )
                        / NULLIF(
                            (COUNT(*) - SUM(CASE WHEN outcome IN ('four', 'six') THEN 1 ELSE 0 END))
                        , 0)
                    ) * 100
                AS NUMERIC), 2
            ) AS nbsr,
            ROUND(
                CAST(
                    (SUM(CASE WHEN CAST(batruns AS INT) = 1 THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100)
                AS NUMERIC), 2
            ) AS singles_pct,
            ROUND(
                CAST(
                    (
                        (0.4 * 
                            (
                                (
                                    (
                                        (SUM(CAST(batruns AS NUMERIC))
                                        - SUM(CASE WHEN outcome IN ('four', 'six') THEN CAST(batruns AS NUMERIC) ELSE 0 END))
                                        / NULLIF(
                                            (COUNT(*) - SUM(CASE WHEN outcome IN ('four', 'six') THEN 1 ELSE 0 END))
                                        , 0)
                                    ) * 100
                                )
                            )
                        )
                        + (0.4 * 
                            (SUM(CASE WHEN CAST(batruns AS INT) = 1 THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100)
                        )
                        + (0.2 *
                            (100 - (SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100))
                        )
                    )
                AS NUMERIC), 2
            ) AS sri
        FROM odi_db
        WHERE LOWER(bat) = LOWER(%s);
    """

    cur.execute(query2, (player,))
    row = cur.fetchone()

    pct_data = {}
    if row:
        pct_data["dot_pct"] = float(row.get("dot_pct") or 0)
        pct_data["boundary_pct"] = float(row.get("boundary_pct") or 0)
        pct_data["nbsr"] = float(row.get("nbsr") or 0)
        pct_data["singles_pct"] = float(row.get("singles_pct") or 0)
        pct_data["sri"] = float(row.get("sri") or 0)
    else:
        pct_data["dot_pct"] = 0
        pct_data["boundary_pct"] = 0
        pct_data["nbsr"] = 0
        pct_data["singles_pct"] = 0
        pct_data["sri"] = 0

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"pp_sr": next((row["strike_rate"] for row in sr_data if row["phase"] == "Powerplay"), 0),
                    "middle_sr": next((row["strike_rate"] for row in sr_data if row["phase"] == "Middle Overs"), 0),
                    "death_sr": next((row["strike_rate"] for row in sr_data if row["phase"] == "Death Overs"), 0),
                    "boundary_pct": pct_data["boundary_pct"] or 0,
                    "dot_pct": pct_data["dot_pct"] or 0,
                    "nbsr":pct_data["nbsr"] or 0,
                    "singles_pct":pct_data["singles_pct"] or 0,
                    "sri":pct_data["sri"]
                    })

@app.route("/api/bowler-skill-profile")
def bowler_skill_profile():
    player = request.args.get("player")
    if not player:
        return jsonify({"error": "Missing player"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Phase-wise economy
    phase_query = """
        SELECT
            CASE 
                WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
                WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle Overs'
                ELSE 'Death Overs'
            END AS phase,
            ROUND(
                CAST(
                    (SUM(CAST(score AS NUMERIC)) / NULLIF(COUNT(ball_id), 0)) * 6 
                AS NUMERIC), 2
            ) AS economy
        FROM odi_db
        WHERE bowl = %s
        GROUP BY phase
        ORDER BY phase;
    """

    cur.execute(phase_query, (player,))
    phase_data = cur.fetchall()

    # Overall skill metrics
    skill_query = """
        SELECT
            ROUND(
                CAST(
                    (SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*)) * 100
                AS NUMERIC), 2
            ) AS dot_pct,
            ROUND(
                CAST(
                    (SUM(CASE WHEN CAST("out" AS BOOLEAN) = TRUE THEN 1 ELSE 0 END)::NUMERIC / COUNT(*)) * 100
                AS NUMERIC), 2
            ) AS wicket_pct,
            ROUND(CAST(SUM(CAST(bowlruns AS FLOAT)) / NULLIF(COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END), 0) AS NUMERIC), 2) AS average,
            ROUND(CAST(CAST(COUNT(*) AS FLOAT) / NULLIF(COUNT(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 END), 0) AS NUMERIC), 2) AS strike_rate,
            ROUND(
                CAST(
                    (SUM(CAST(score AS NUMERIC)) / NULLIF(COUNT(ball_id),0)) * 6
                AS NUMERIC), 2
            ) AS overall_econ
        FROM odi_db
        WHERE bowl = %s;
    """

    cur.execute(skill_query, (player,))
    skill_data = cur.fetchone()

    # Compute Bowler Efficiency Index (BEI)
    bei_query = """
        SELECT
            ROUND(
                CAST(
                    (
                        (0.3 * (100 - ((SUM(CAST(score AS NUMERIC)) / NULLIF(COUNT(ball_id),0)) * 6))) +
                        (0.3 * ((SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100))) +
                        (0.2 * ((SUM(CASE WHEN CAST("out" AS BOOLEAN) = TRUE THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100))) +
                        (0.2 * (100 - (SUM(CASE WHEN outcome IN ('four', 'six') THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100)))
                    )
                AS NUMERIC), 2
            ) AS bei
        FROM odi_db
        WHERE bowl = %s;
    """

    cur.execute(bei_query, (player,))
    bei_data = cur.fetchone()

    cur.close()
    conn.close()

    return jsonify({
        "phase_data": phase_data,
        "skills": skill_data,
        "bei": bei_data
    })

@app.route("/api/global-phase-benchmarks")
def global_phase_benchmarks():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    query = """
        WITH player_phase_stats AS (
            SELECT 
                bat,
                CASE 
                    WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
                    WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle'
                    ELSE 'Death'
                END AS phase,
                SUM(CAST(batruns AS FLOAT)) AS total_runs,
                SUM(CAST(ballfaced AS FLOAT)) AS total_balls,
                SUM(CASE WHEN LOWER(outcome) IN ('four', 'six') THEN 1 ELSE 0 END)::FLOAT AS boundaries,
                SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::FLOAT AS dots,
                SUM(CASE WHEN CAST("out" AS BOOLEAN) = TRUE THEN 1 ELSE 0 END)::FLOAT AS outs,
                COUNT(*)::FLOAT AS total_balls_faced
            FROM odi_db
            WHERE bat IS NOT NULL
            GROUP BY bat, phase
        ),
        aggregated AS (
            SELECT
                bat,
                phase,
                (total_runs / NULLIF(total_balls, 0)) * 100 AS sr,
                (boundaries / NULLIF(total_balls_faced, 0)) * 100 AS boundary_pct,
                (dots / NULLIF(total_balls_faced, 0)) * 100 AS dot_pct,
                ((total_balls_faced - boundaries - dots) / NULLIF(total_balls_faced, 0)) * 100 AS sri,
                (total_runs / NULLIF(outs, 0)) AS average
            FROM player_phase_stats
        )
        SELECT 
            phase,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY sr)::NUMERIC, 2) AS sr_95,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY boundary_pct)::NUMERIC, 2) AS boundary_95,
            ROUND(PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY dot_pct)::NUMERIC, 2) AS dot_95,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY sri)::NUMERIC, 2) AS sri_95,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY average)::NUMERIC, 2) AS avg_95
        FROM aggregated
        GROUP BY phase
        ORDER BY 
            CASE 
                WHEN phase = 'Powerplay' THEN 1
                WHEN phase = 'Middle' THEN 2
                WHEN phase = 'Death' THEN 3
            END;
    """

    cur.execute(query)
    rows = cur.fetchall()

    global_query = """
    WITH player_agg AS (
        SELECT 
            bat,
            SUM(CAST(batruns AS NUMERIC)) AS total_runs,
            COUNT(*)::NUMERIC AS total_balls,
            SUM(CASE WHEN outcome IN ('four', 'six') THEN 1 ELSE 0 END)::NUMERIC AS boundaries,
            SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC AS dots,
            SUM(CASE WHEN CAST(batruns AS INT) = 1 THEN 1 ELSE 0 END)::NUMERIC AS singles,
            SUM(CASE WHEN outcome IN ('four', 'six') THEN CAST(batruns AS NUMERIC) ELSE 0 END)::NUMERIC AS boundary_runs
        FROM odi_db
        WHERE bat IS NOT NULL
        GROUP BY bat
    ),
    derived AS (
        SELECT
            bat,
            ROUND(
                CAST(
                    (
                        (0.4 * 
                            (
                                (
                                    (
                                        (total_runs - boundary_runs)
                                        / NULLIF((total_balls - boundaries), 0)
                                    ) * 100
                                )
                            )
                        )
                        + (0.4 * (singles / NULLIF(total_balls, 0) * 100))
                        + (0.2 * (100 - (dots / NULLIF(total_balls, 0) * 100)))
                    )
                AS NUMERIC), 2
            ) AS sri,
            ROUND((boundaries / NULLIF(total_balls, 0)) * 100, 2) AS boundary_pct
        FROM player_agg
    )
    SELECT 
        ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY sri)::NUMERIC, 2) AS sri_95_global,
        ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY boundary_pct)::NUMERIC, 2) AS boundary_95_global
    FROM derived;
"""
    cur.execute(global_query)
    dataaa = cur.fetchone()
    cur.close()
    conn.close()

    benchmarks = {row["phase"]: row for row in rows}
    return jsonify({"phase":benchmarks,"global":dataaa})

@app.route("/api/bowlers-global-benchmarks")
def bowlers_global_benchmarks():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Phase-based 95th percentiles (Powerplay, Middle, Death)
    phase_query = """
        SELECT
            phase,
            ROUND(PERCENTILE_CONT(0.05) WITHIN GROUP (
                ORDER BY economy
            )::NUMERIC, 2) AS econ_95,
            ROUND(PERCENTILE_CONT(0.05) WITHIN GROUP (
                ORDER BY strike_rate
            )::NUMERIC, 2) AS sr_95,
            ROUND(PERCENTILE_CONT(0.05) WITHIN GROUP (
                ORDER BY average
            )::NUMERIC, 2) AS avg_95
        FROM (
            SELECT
                CASE 
                    WHEN CAST(over AS INTEGER) <= 10 THEN 'Powerplay'
                    WHEN CAST(over AS INTEGER) BETWEEN 11 AND 40 THEN 'Middle'
                    ELSE 'Death'
                END AS phase,
                (SUM(CAST(score AS FLOAT)) / NULLIF(COUNT(ball_id), 0)) * 6 AS economy,
                (CAST(COUNT(ball_id) AS FLOAT) / NULLIF(SUM(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 ELSE 0 END), 0)) AS strike_rate,
                (SUM(CAST(bowlruns AS FLOAT)) / NULLIF(SUM(CASE WHEN outcome = 'out' AND dismissal != 'run out' THEN 1 ELSE 0 END), 0)) AS average
            FROM odi_db
            WHERE bowl IS NOT NULL
            GROUP BY phase, bowl
        ) sub
        GROUP BY phase
        ORDER BY phase;
    """

    cur.execute(phase_query)
    phase_rows = cur.fetchall()

    # Global metrics (dot%, wicket%, BEI)
    global_query = """
        SELECT
        ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY dot_pct)::NUMERIC, 2) AS dot_95_global,
        ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY wicket_pct)::NUMERIC, 2) AS wicket_95_global,
        ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY bei)::NUMERIC, 2) AS bei_95_global
        FROM (
            SELECT
                bowl,
                (SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*)) * 100 AS dot_pct,

                (SUM(CASE WHEN CAST("out" AS BOOLEAN) = TRUE THEN 1 ELSE 0 END)::NUMERIC / COUNT(*)) * 100 AS wicket_pct,

                (
                    (0.3 * (100 - ((SUM(CAST(score AS NUMERIC)) / NULLIF(COUNT(ball_id), 0)) * 6))) +
                    (0.3 * ((SUM(CASE WHEN LOWER(outcome) = 'no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100))) +
                    (0.2 * ((SUM(CASE WHEN CAST("out" AS BOOLEAN) = TRUE THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100))) +
                    (0.2 * (100 - (SUM(CASE WHEN outcome IN ('four', 'six') THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100)))
                ) AS bei
            FROM odi_db
            WHERE bowl IS NOT NULL
            GROUP BY bowl
        ) sub;
    """

    cur.execute(global_query)
    global_row = cur.fetchone()

    cur.close()
    conn.close()

    # Convert list to dict
    phase_dict = {row["phase"]: row for row in phase_rows}

    return jsonify({
        "phase": phase_dict,
        "global": global_row
    })

@app.route("/api/batter-zone-summary")
def batter_zone_summary():
    player = request.args.get("player")
    bowl_style = request.args.get("bowl_style")

    if not player:
        return jsonify({"error": "Missing player"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query = f"""
        SELECT
            ROUND(SUM(CAST(batruns AS NUMERIC))/NULLIF(COUNT(ball_id),0)*100,2) AS strike_rate,
            ROUND(SUM(CASE WHEN outcome IN ('four','six') THEN 1 ELSE 0 END)::NUMERIC/COUNT(*)*100,2) AS boundary_pct,
            ROUND(SUM(CASE WHEN LOWER(outcome)='no run' THEN 1 ELSE 0 END)::NUMERIC/COUNT(*)*100,2) AS dot_pct,
            ROUND(
                    CASE WHEN COUNT(control) > 0 
                        THEN (
                            SUM(
                                COALESCE(
                                    NULLIF(
                                        NULLIF(LOWER(control), 'nan'),
                                        ''
                                    )::NUMERIC,
                                    0
                                )
                            ) / COUNT(control) * 100
                        )
                        ELSE 0 END, 2
                ) AS ctrl_pct,
            ROUND(
                CAST(
                    (
                        (0.4 * 
                            (
                                ((SUM(CAST(batruns AS NUMERIC)) - 
                                SUM(CASE WHEN outcome IN ('four', 'six') THEN CAST(batruns AS NUMERIC) ELSE 0 END))
                                / NULLIF(
                                    (COUNT(*) - SUM(CASE WHEN outcome IN ('four', 'six') THEN 1 ELSE 0 END))
                                , 0)) * 100
                            )
                        )
                        + (0.4 * (SUM(CASE WHEN CAST(batruns AS INT)=1 THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100))
                        + (0.2 * (100 - (SUM(CASE WHEN LOWER(outcome)='no run' THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100)))
                    ) AS NUMERIC
                ), 2
            ) AS sri
        FROM odi_db
        WHERE bat=%s
        { "AND bowl_kind ILIKE %s" if bowl_style else "" }
    """

    params = [player]
    if bowl_style:
        params.append(f"%{bowl_style}%")

    cur.execute(query, params)
    result = cur.fetchone()
    cur.close()
    conn.close()

    return jsonify(result or {})


if __name__ == '__main__':
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)