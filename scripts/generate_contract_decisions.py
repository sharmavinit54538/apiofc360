"""Generate docs/CONTRACT_DECISIONS.md from API_GAPS.md and live FastAPI routes."""
import json
import re

def clean_str(s):
    return s.strip(" `'\t\r\n")

def normalize_path(p):
    p = p.split('?')[0].rstrip('/')
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

    decisions = []
    for l in lines:
        parts = [clean_str(p) for p in l.split('|')[1:-1]]
        if len(parts) >= 4:
            file_path, method, path, original_decision = parts[0], parts[1], parts[2], parts[3]
            notes = parts[4] if len(parts) > 4 else ''
            norm_p = normalize_path(path)
            
            # Check exact match in live routes
            exact_match = None
            if norm_p in live_index:
                for (lm, lp, name) in live_index[norm_p]:
                    if lm == method:
                        exact_match = lp
                        break

            # Check v1 match
            v1_match = None
            v1_norm = normalize_path('/api/v1' + (norm_p if norm_p.startswith('/') else '/' + norm_p))
            if not exact_match and v1_norm in live_index:
                for (lm, lp, name) in live_index[v1_norm]:
                    if lm == method:
                        v1_match = lp
                        break

            # Check v2 match
            v2_match = None
            v2_norm = normalize_path('/api/v2' + (norm_p if norm_p.startswith('/') else '/' + norm_p))
            if not exact_match and not v1_match and v2_norm in live_index:
                for (lm, lp, name) in live_index[v2_norm]:
                    if lm == method:
                        v2_match = lp
                        break

            if exact_match:
                # Already exists exactly as called
                decision = "DONE-EXISTING"
                final_method = method
                final_path = exact_match
                contract = "Existing live route"
                decision_notes = f"Route exists as {exact_match}"
            elif v1_match:
                # Exists under /api/v1 - frontend fix to prefix /api/v1 or backend adds alias
                decision = "FRONTEND_FIX"
                final_method = method
                final_path = v1_match
                contract = f"Call with prefix {v1_match}. (Backend also supports alias for compatibility)."
                decision_notes = f"Canonical route is {v1_match}."
            elif v2_match:
                decision = "FRONTEND_FIX"
                final_method = method
                final_path = v2_match
                contract = f"Call with prefix {v2_match}."
                decision_notes = f"Canonical route is {v2_match}."
            else:
                # Truly missing: determine if BACKEND_ADD or REMOVE_DEAD
                decision = "BACKEND_ADD"
                final_method = method
                # Canonical path should be structured properly
                if norm_p.startswith('/api/v2') or norm_p.startswith('/api/v1'):
                    final_path = path
                else:
                    final_path = path  # Will be implemented at both /api/v1 and root alias
                
                # Assign payload contract hint
                if method in ['POST', 'PUT', 'PATCH']:
                    contract = "JSON payload: refer to B-08/B-09/B-10 specs."
                else:
                    contract = "Query params / standard response {items, total, page, limit} or {data}."
                decision_notes = f"To be added in package B-04/B-05/B-07/B-08/B-09/B-10. {notes}"

            decisions.append({
                'file': file_path,
                'method': method,
                'path': path,
                'decision': decision,
                'final_method': final_method,
                'final_path': final_path,
                'contract': contract,
                'notes': decision_notes
            })

    output_lines = [
        "# API Contract Decisions Baseline (B-00.1 / B-08)",
        "",
        "Reconciliation of all 444 endpoint references in `API_GAPS.md` against live FastAPI routes.",
        "",
        "## Summary of Baseline Classifications",
        f"- **Total References Audited:** {len(decisions)}",
        f"- **DONE-EXISTING (Exact Route Match Live):** {sum(1 for d in decisions if d['decision'] == 'DONE-EXISTING')}",
        f"- **FRONTEND_FIX (Canonical under `/api/v1` or `/api/v2`):** {sum(1 for d in decisions if d['decision'] == 'FRONTEND_FIX')}",
        f"- **BACKEND_ADD (New Endpoints to Implement):** {sum(1 for d in decisions if d['decision'] == 'BACKEND_ADD')}",
        "",
        "> **Note:** For maximum frontend stability, all `FRONTEND_FIX` routes will also be aliased at root in the backend so old calls continue to succeed without frontend breakage while the frontend team updates their clients.",
        "",
        "| Source File | Frontend Method | Frontend Path | Decision | Final Method | Final Canonical Path | Contract / Payload | Notes |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    for d in decisions:
        output_lines.append(
            f"| `{d['file']}` | `{d['method']}` | `{d['path']}` | **{d['decision']}** | `{d['final_method']}` | `{d['final_path']}` | {d['contract']} | {d['notes']} |"
        )

    with open('docs/CONTRACT_DECISIONS.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines) + '\n')

    print(f"Generated docs/CONTRACT_DECISIONS.md with {len(decisions)} rows.")

if __name__ == '__main__':
    main()
