#!/usr/bin/env python3
"""
Simple web server for Stormgate Replay Stats
Run: python server.py
Then open http://localhost:8080
"""

import os
import sys
import json
import webbrowser
import threading
import traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parse_sgreplay import SGReplayParser as ReplayParser
from collections import defaultdict, Counter
try:
    from ability_lookup import AbilityLookup
    ability_lookup = AbilityLookup()
except ImportError:
    ability_lookup = None


def compute_summary(replays_data, main_player):
    """Compute comprehensive statistics for the main player across replays."""
    stats = {
        'main_player': main_player,
        'total_games': 0,
        'wins': 0,
        'losses': 0,
        # Race stats
        'race_picks': defaultdict(int),
        'race_wins': defaultdict(int),
        'race_losses': defaultdict(int),
        # Matchup stats (vs opponent race)
        'matchup_games': defaultdict(int),
        'matchup_wins': defaultdict(int),
        # First 3 buildings by matchup
        'first_buildings_by_matchup': defaultdict(lambda: defaultdict(lambda: {'count': 0, 'wins': 0})),
        # First stormgate reward
        'first_reward': defaultdict(lambda: {'count': 0, 'wins': 0}),
        # Map stats
        'map_games': defaultdict(int),
        'map_wins': defaultdict(int),
        # Game length stats
        'game_lengths': [],
        'game_lengths_wins': [],
        'game_lengths_losses': [],
        # Changelist breakdown
        'changelist_games': defaultdict(int),
        'changelist_wins': defaultdict(int),
        # Teammate stats (for 2v2)
        'teammate_games': defaultdict(int),
        'teammate_wins': defaultdict(int),
        # Opening buildings sequence
        'opening_sequences': defaultdict(lambda: {'count': 0, 'wins': 0}),
    }

    for replay in replays_data:
        players = replay.get('players', {})
        teams = replay.get('player_teams', {})
        factions = replay.get('player_factions', {})
        result = replay.get('game_result', {})
        buildings = replay.get('building_orders', {})
        rewards = replay.get('stormgate_rewards', {})
        changelist = replay.get('header', {}).get('changelist', 0)
        map_name = replay.get('map', 'Unknown')
        duration = replay.get('duration_seconds', 0)

        # Find main player's slot
        main_slot = None
        for slot, name in players.items():
            if name == main_player:
                main_slot = slot
                break

        if main_slot is None:
            continue

        main_slot_int = int(main_slot) if isinstance(main_slot, str) else main_slot
        main_faction = factions.get(main_slot) or factions.get(main_slot_int) or 'Unknown'
        main_team = teams.get(main_slot) or teams.get(main_slot_int)

        # Determine win/loss from player_results
        player_results = result.get('player_results', {})
        player_result = player_results.get(str(main_slot)) or player_results.get(main_slot)
        is_win = player_result == 'win'

        stats['total_games'] += 1
        if is_win:
            stats['wins'] += 1
        else:
            stats['losses'] += 1

        # Race picks
        stats['race_picks'][main_faction] += 1
        if is_win:
            stats['race_wins'][main_faction] += 1
        else:
            stats['race_losses'][main_faction] += 1

        # Find opponents
        opponents = []
        teammates = []
        for slot, name in players.items():
            slot_int = int(slot) if isinstance(slot, str) else slot
            if name == main_player:
                continue
            player_team = teams.get(slot) or teams.get(slot_int)
            player_faction = factions.get(slot) or factions.get(slot_int) or 'Unknown'
            if player_team == main_team:
                teammates.append({'name': name, 'faction': player_faction})
            else:
                opponents.append({'name': name, 'faction': player_faction})

        # Matchup stats (vs opponent races)
        for opp in opponents:
            matchup = f"{main_faction} vs {opp['faction']}"
            stats['matchup_games'][matchup] += 1
            if is_win:
                stats['matchup_wins'][matchup] += 1

        # Teammate stats
        for tm in teammates:
            stats['teammate_games'][tm['name']] += 1
            if is_win:
                stats['teammate_wins'][tm['name']] += 1

        # First 3 buildings
        main_buildings = buildings.get(main_slot) or buildings.get(str(main_slot)) or []
        # Filter out non-production buildings and inferred for opening analysis
        prod_buildings = [b for b in main_buildings if not b.get('inferred') and
                         b.get('building_name') not in ['Therium Extractor', 'Therium Deposit', 'Supply', 'Link Node', 'PowerBank', 'Collection Array']]

        first_3 = [b.get('building_name', 'Unknown') for b in prod_buildings[:3]]
        if first_3:
            # By matchup
            for opp in opponents:
                matchup = f"{main_faction} vs {opp['faction']}"
                for i, bldg in enumerate(first_3):
                    key = f"B{i+1}: {bldg}"
                    stats['first_buildings_by_matchup'][matchup][key]['count'] += 1
                    if is_win:
                        stats['first_buildings_by_matchup'][matchup][key]['wins'] += 1

            # Opening sequence (first 3 buildings as a combo)
            opening = ' → '.join(first_3)
            stats['opening_sequences'][opening]['count'] += 1
            if is_win:
                stats['opening_sequences'][opening]['wins'] += 1

        # First stormgate reward
        main_rewards = rewards.get(main_slot) or rewards.get(str(main_slot)) or []
        if main_rewards:
            first_reward = main_rewards[0].get('reward_name', 'Unknown')
            stats['first_reward'][first_reward]['count'] += 1
            if is_win:
                stats['first_reward'][first_reward]['wins'] += 1

        # Map stats
        stats['map_games'][map_name] += 1
        if is_win:
            stats['map_wins'][map_name] += 1

        # Game length
        if duration > 0:
            stats['game_lengths'].append(duration)
            if is_win:
                stats['game_lengths_wins'].append(duration)
            else:
                stats['game_lengths_losses'].append(duration)

        # Changelist
        stats['changelist_games'][changelist] += 1
        if is_win:
            stats['changelist_wins'][changelist] += 1

    # Convert defaultdicts to regular dicts for JSON serialization
    def to_dict(d):
        if isinstance(d, defaultdict):
            return {k: to_dict(v) for k, v in d.items()}
        return d

    result = {
        'main_player': stats['main_player'],
        'total_games': stats['total_games'],
        'wins': stats['wins'],
        'losses': stats['losses'],
        'win_rate': stats['wins'] / stats['total_games'] * 100 if stats['total_games'] > 0 else 0,
        'race_stats': {},
        'matchup_stats': {},
        'first_buildings_by_matchup': {},
        'first_reward_stats': {},
        'opening_sequences': {},
        'map_stats': {},
        'teammate_stats': {},
        'changelist_stats': {},
        'game_length_stats': {},
    }

    # Race stats
    for race in stats['race_picks']:
        games = stats['race_picks'][race]
        wins = stats['race_wins'][race]
        result['race_stats'][race] = {
            'games': games,
            'wins': wins,
            'losses': games - wins,
            'pick_rate': games / stats['total_games'] * 100 if stats['total_games'] > 0 else 0,
            'win_rate': wins / games * 100 if games > 0 else 0,
        }

    # Matchup stats
    for matchup in stats['matchup_games']:
        games = stats['matchup_games'][matchup]
        wins = stats['matchup_wins'][matchup]
        result['matchup_stats'][matchup] = {
            'games': games,
            'wins': wins,
            'losses': games - wins,
            'win_rate': wins / games * 100 if games > 0 else 0,
        }

    # First buildings by matchup
    for matchup, bldgs in stats['first_buildings_by_matchup'].items():
        matchup_total = stats['matchup_games'].get(matchup, 1)
        result['first_buildings_by_matchup'][matchup] = {}
        for bldg, data in sorted(bldgs.items(), key=lambda x: -x[1]['count']):
            result['first_buildings_by_matchup'][matchup][bldg] = {
                'count': data['count'],
                'percentage': data['count'] / matchup_total * 100 if matchup_total > 0 else 0,
                'wins': data['wins'],
                'win_rate': data['wins'] / data['count'] * 100 if data['count'] > 0 else 0,
            }

    # First reward stats
    total_rewards = sum(d['count'] for d in stats['first_reward'].values())
    for reward, data in sorted(stats['first_reward'].items(), key=lambda x: -x[1]['count']):
        result['first_reward_stats'][reward] = {
            'count': data['count'],
            'percentage': data['count'] / total_rewards * 100 if total_rewards > 0 else 0,
            'wins': data['wins'],
            'win_rate': data['wins'] / data['count'] * 100 if data['count'] > 0 else 0,
        }

    # Opening sequences
    for opening, data in sorted(stats['opening_sequences'].items(), key=lambda x: -x[1]['count'])[:20]:
        result['opening_sequences'][opening] = {
            'count': data['count'],
            'percentage': data['count'] / stats['total_games'] * 100 if stats['total_games'] > 0 else 0,
            'wins': data['wins'],
            'win_rate': data['wins'] / data['count'] * 100 if data['count'] > 0 else 0,
        }

    # Map stats
    for map_name in stats['map_games']:
        games = stats['map_games'][map_name]
        wins = stats['map_wins'][map_name]
        result['map_stats'][map_name] = {
            'games': games,
            'wins': wins,
            'win_rate': wins / games * 100 if games > 0 else 0,
        }

    # Teammate stats
    for name in stats['teammate_games']:
        games = stats['teammate_games'][name]
        wins = stats['teammate_wins'][name]
        result['teammate_stats'][name] = {
            'games': games,
            'wins': wins,
            'win_rate': wins / games * 100 if games > 0 else 0,
        }

    # Changelist stats
    for cl in sorted(stats['changelist_games'].keys(), reverse=True):
        games = stats['changelist_games'][cl]
        wins = stats['changelist_wins'][cl]
        result['changelist_stats'][cl] = {
            'games': games,
            'wins': wins,
            'win_rate': wins / games * 100 if games > 0 else 0,
        }

    # Game length stats
    if stats['game_lengths']:
        avg_length = sum(stats['game_lengths']) / len(stats['game_lengths'])
        avg_win_length = sum(stats['game_lengths_wins']) / len(stats['game_lengths_wins']) if stats['game_lengths_wins'] else 0
        avg_loss_length = sum(stats['game_lengths_losses']) / len(stats['game_lengths_losses']) if stats['game_lengths_losses'] else 0
        result['game_length_stats'] = {
            'avg_seconds': avg_length,
            'avg_formatted': f"{int(avg_length // 60)}:{int(avg_length % 60):02d}",
            'avg_win_seconds': avg_win_length,
            'avg_win_formatted': f"{int(avg_win_length // 60)}:{int(avg_win_length % 60):02d}",
            'avg_loss_seconds': avg_loss_length,
            'avg_loss_formatted': f"{int(avg_loss_length // 60)}:{int(avg_loss_length % 60):02d}",
            'shortest': min(stats['game_lengths']),
            'longest': max(stats['game_lengths']),
        }

    return result

# Default to Stormgate's saved replays folder on Windows
def get_default_replays_dir():
    """Get the default Stormgate replays directory."""
    if sys.platform == 'win32':
        local_app_data = os.environ.get('LOCALAPPDATA', '')
        if local_app_data:
            stormgate_replays = os.path.join(local_app_data, 'Stormgate', 'Saved', 'Replays')
            if os.path.exists(stormgate_replays):
                return stormgate_replays
    # Fallback to replays folder in project directory
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'replays')

REPLAYS_DIR = get_default_replays_dir()


class ReplayHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Serve files from the web directory
        super().__init__(*args, directory=os.path.dirname(os.path.abspath(__file__)), **kwargs)

    def do_GET(self):
        if self.path == '/api/replays':
            self.send_replay_list()
        elif self.path.startswith('/api/parse?'):
            self.parse_replay()
        elif self.path.startswith('/api/summary'):
            self.get_summary()
        else:
            super().do_GET()

    def get_summary(self):
        """Parse recent replays and compute summary statistics"""
        query = self.path.split('?', 1)[1] if '?' in self.path else ''
        params = parse_qs(query)
        changelist_filter = params.get('changelist', [None])[0]
        limit = int(params.get('limit', ['30'])[0])
        selected_player = params.get('player', [None])[0]
        selected_dir = params.get('dir', [None])[0]

        # Available directories
        available_dirs = [
            {'path': REPLAYS_DIR, 'name': 'Stormgate Replays'},
            {'path': os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'replays'), 'name': 'Project Replays'},
        ]
        # Filter to only existing directories
        available_dirs = [d for d in available_dirs if os.path.exists(d['path'])]

        # Collect replay files from selected or all directories
        replay_files = []
        seen_names = set()

        if selected_dir:
            search_dirs = [selected_dir]
        else:
            search_dirs = [d['path'] for d in available_dirs]

        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            try:
                for f in os.listdir(search_dir):
                    if f.endswith('.SGReplay') and f not in seen_names:
                        filepath = os.path.join(search_dir, f)
                        replay_files.append({
                            'name': f,
                            'path': filepath,
                            'mtime': os.path.getmtime(filepath)
                        })
                        seen_names.add(f)
            except OSError:
                continue

        # Sort by modification time (most recent first)
        replay_files.sort(key=lambda r: r['mtime'], reverse=True)

        # Parse replays concurrently
        def parse_replay_file(replay_file):
            """Parse a single replay file and return data or None on error."""
            try:
                parser = ReplayParser(replay_file['path'], ability_lookup=ability_lookup)
                parser.load()
                parser.parse()
                data = parser.to_json(include_actions=False)
                return {'success': True, 'data': data, 'name': replay_file['name']}
            except Exception as e:
                print(f"\n{'='*60}")
                print(f"Error parsing {replay_file['name']}: {e}")
                print(f"{'='*60}")
                traceback.print_exc()
                print(f"{'='*60}\n")
                return {'success': False, 'name': replay_file['name']}

        replays_data = []
        player_counts = Counter()
        changelists = set()

        # Use ThreadPoolExecutor for concurrent parsing
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(parse_replay_file, rf): rf for rf in replay_files}
            for future in as_completed(futures):
                result = future.result()
                if result['success']:
                    data = result['data']
                    # Track changelist
                    cl = data.get('header', {}).get('changelist', 0)
                    changelists.add(cl)

                    # Count player occurrences
                    for name in data.get('players', {}).values():
                        player_counts[name] += 1

                    replays_data.append(data)

        # Get list of all players for the dropdown
        all_players = [p for p, _ in player_counts.most_common()]

        # Use selected player or default to most frequently seen
        if selected_player and selected_player in all_players:
            main_player = selected_player
        else:
            main_player = player_counts.most_common(1)[0][0] if player_counts else None

        # Default to latest changelist if none specified
        if not changelist_filter and changelists:
            changelist_filter = str(max(changelists))

        # Filter by changelist if specified
        if changelist_filter:
            cl_int = int(changelist_filter)
            replays_data = [r for r in replays_data if r.get('header', {}).get('changelist') == cl_int]

        # Limit to requested number
        replays_data = replays_data[:limit]

        if not main_player or not replays_data:
            self.send_json({
                'error': 'No replays found or unable to identify main player',
                'changelists': sorted(changelists, reverse=True),
                'total_replays_available': len(replay_files),
                'available_players': all_players,
                'available_dirs': available_dirs,
            })
            return

        # Compute summary statistics
        summary = compute_summary(replays_data, main_player)
        summary['changelists'] = sorted(changelists, reverse=True)
        summary['total_replays_available'] = len(replay_files)
        summary['replays_analyzed'] = len(replays_data)
        summary['changelist_filter'] = changelist_filter
        summary['available_players'] = all_players
        summary['available_dirs'] = available_dirs
        summary['selected_dir'] = selected_dir

        self.send_json(summary)

    def do_POST(self):
        if self.path == '/api/upload':
            self.handle_upload()
        else:
            self.send_error(404)

    def send_json(self, data, status=200):
        response = json.dumps(data, indent=2)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(response.encode()))
        self.end_headers()
        self.wfile.write(response.encode())

    def send_replay_list(self):
        """List all .SGReplay files from multiple directories"""
        replays = []
        seen_names = set()

        # Directories to search for replays
        search_dirs = [
            REPLAYS_DIR,  # Default Stormgate replays folder
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'replays'),  # Project replays folder
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # Project root
        ]

        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            try:
                for f in os.listdir(search_dir):
                    if f.endswith('.SGReplay') and f not in seen_names:
                        filepath = os.path.join(search_dir, f)
                        replays.append({
                            'name': f,
                            'size': os.path.getsize(filepath),
                            'path': filepath
                        })
                        seen_names.add(f)
            except OSError:
                continue

        # Sort by name (most recent first assuming date-based naming)
        replays.sort(key=lambda r: r['name'], reverse=True)
        self.send_json(replays)

    def parse_replay(self):
        """Parse a replay file and return JSON"""
        query = self.path.split('?', 1)[1] if '?' in self.path else ''
        params = parse_qs(query)
        filename = params.get('file', [''])[0]

        if not filename:
            self.send_json({'error': 'No file specified'}, 400)
            return

        # Search in same directories as send_replay_list
        search_dirs = [
            REPLAYS_DIR,
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'replays'),
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ]

        filepath = None
        for search_dir in search_dirs:
            candidate = os.path.join(search_dir, filename)
            if os.path.exists(candidate):
                filepath = candidate
                break

        if not filepath:
            self.send_json({'error': f'File not found: {filename}'}, 404)
            return

        try:
            parser = ReplayParser(filepath, ability_lookup=ability_lookup)
            parser.load()
            parser.parse()
            data = parser.to_json(include_actions=True)
            self.send_json(data)
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"ERROR parsing replay: {filepath}")
            print(f"{'='*60}")
            traceback.print_exc()
            print(f"{'='*60}\n")
            self.send_json({'error': str(e)}, 500)

    def handle_upload(self):
        """Handle uploaded replay file"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_json({'error': 'No file uploaded'}, 400)
            return

        # Read the file data
        file_data = self.rfile.read(content_length)

        # Save to temp file and parse
        try:
            with tempfile.NamedTemporaryFile(suffix='.SGReplay', delete=False) as tmp:
                tmp.write(file_data)
                tmp_path = tmp.name

            parser = ReplayParser(tmp_path, ability_lookup=ability_lookup)
            parser.load()
            parser.parse()
            data = parser.to_json(include_actions=True)

            os.unlink(tmp_path)
            self.send_json(data)
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"ERROR parsing uploaded replay")
            print(f"{'='*60}")
            traceback.print_exc()
            print(f"{'='*60}\n")
            if 'tmp_path' in locals():
                try:
                    os.unlink(tmp_path)
                except:
                    pass
            self.send_json({'error': str(e)}, 500)


def main():
    port = 8080
    url = f"http://localhost:{port}"

    server = HTTPServer(('localhost', port), ReplayHandler)
    print(f"Stormgate Replay Stats running at {url}")
    print(f"Replays directory: {REPLAYS_DIR}")
    print("Press Ctrl+C to stop")

    # Open browser after a short delay to ensure server is ready
    def open_browser():
        webbrowser.open(url)
    threading.Timer(0.5, open_browser).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()
