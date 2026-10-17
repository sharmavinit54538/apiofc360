"""Script to accurately reconcile frontend API_GAPS.md with live FastAPI routes."""
import json
import re

def clean_str(s):
    # Strip backticks, quotes, whitespace
    return s.strip(" `'\t\r\n")

def normalize_path(p):
    p = p.split('?')[0].rstrip('/')
    # Normalize ${...} and {...} to {param}
    p = re.sub(r'\$\{[^}]+\}', '{param}', p)
    p = re.sub(r'\{[^}]+\}', '{param}', p)
    return p

def main():
    with open('all_live_fastapi_routes.json', 'r') as f:
        live_routes = json.load(f)

    live_index = {}
    for r in live_routes:
        norm = normalize_path(r['path'])
        for m in r['methods']:
            live_index.setdefault(norm, []).append((m, r['path'], r.get('name', '')))

    with open('docs/API_GAPS.md', 'r') as f:
        lines = [l.strip() for l in f if l.strip().startswith('|') and not l.strip().startswith('| :') and not l.strip().startswith('| File')]

    exact_matches = []
    v1_matches = []
    v2_matches = []
    truly_missing = []

    for l in lines:
        parts = [clean_str(p) for p in l.split('|')[1:-1]]
        if len(parts) >= 4:
            file_path, method, path, decision = parts[0], parts[1], parts[2], parts[3]
            notes = parts[4] if len(parts) > 4 else ''
            norm_p = normalize_path(path)
            
            # Check exact
            matched = False
            if norm_p in live_index:
                for (lm, lp, name) in live_index[norm_p]:
                    if lm == method:
                        exact_matches.append((file_path, method, path, lp, name, notes))
                        matched = True
                        break
            if matched:
                continue

            # Check v1
            v1_norm = normalize_path('/api/v1' + (norm_p if norm_p.startswith('/') else '/' + norm_p))
            if v1_norm in live_index:
                for (lm, lp, name) in live_index[v1_norm]:
                    if lm == method:
                        v1_matches.append((file_path, method, path, lp, name, notes))
                        matched = True
                        break
            if matched:
                continue

            # Check v2
            v2_norm = normalize_path('/api/v2' + (norm_p if norm_p.startswith('/') else '/' + norm_p))
            if v2_norm in live_index:
                for (lm, lp, name) in live_index[v2_norm]:
                    if lm == method:
                        v2_matches.append((file_path, method, path, lp, name, notes))
                        matched = True
                        break
            if matched:
                continue

            truly_missing.append((file_path, method, path, norm_p, notes))

    print(f"Total gaps in API_GAPS.md: {len(lines)}")
    print(f"Exact match live in backend: {len(exact_matches)}")
    print(f"Match with /api/v1 prefix: {len(v1_matches)}")
    print(f"Match with /api/v2 prefix: {len(v2_matches)}")
    print(f"Truly missing from backend: {len(truly_missing)}")

    # Unique truly missing paths
    unique_missing = {}
    for (f, m, p, norm_p, notes) in truly_missing:
        unique_missing.setdefault((m, norm_p), []).append((p, f, notes))

    print(f"Unique truly missing (method, normalized_path): {len(unique_missing)}")
    with open('scripts/truly_missing.json', 'w') as f:
        json.dump([{'method': k[0], 'path': k[1], 'count': len(v), 'sample_original': v[0][0], 'notes': v[0][2]} for k, v in unique_missing.items()], f, indent=2)

if __name__ == '__main__':
    main()
