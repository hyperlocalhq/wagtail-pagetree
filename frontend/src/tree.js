// Pure helpers for tree-building, expansion state, and search highlighting.
// No React in here — easier to reason about and trivially testable.

const INITIAL_AUTO_EXPAND_DEPTH = 2;

// Group nodes by parent_id. Nodes with parent_id === null are roots.
// Returns Map<parentId|null, Node[]> preserving the original order
// (backend already orders by path, so child order is correct).
export function groupByParent(nodes) {
  const m = new Map();
  m.set(null, []);
  for (const n of nodes) {
    const key = n.parent_id == null ? null : n.parent_id;
    if (!m.has(key)) m.set(key, []);
    m.get(key).push(n);
  }
  return m;
}

// Set of node ids to auto-expand on first render. Walks the tree and
// expands every node at depth < target so the user lands on a usable
// view (depth 2 visible by default per the M2 acceptance criteria).
export function defaultExpansion(nodes, depth = INITIAL_AUTO_EXPAND_DEPTH) {
  const min = Math.min(...nodes.map((n) => n.depth));
  const result = new Set();
  for (const n of nodes) {
    if (n.depth - min < depth) result.add(n.id);
  }
  return result;
}

// Returns the set of ancestor ids for a given node id, walking up via
// parent_id. Used by search auto-expand.
export function ancestorIds(nodes, nodeId) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out = new Set();
  let cur = byId.get(nodeId);
  while (cur && cur.parent_id != null) {
    out.add(cur.parent_id);
    cur = byId.get(cur.parent_id);
  }
  return out;
}

// Wrap each occurrence of `query` (case-insensitive) in <mark>. Returns
// an array of { kind: "text"|"match", value } chunks for safe React render.
export function highlight(text, query) {
  if (!query || !text) return [{ kind: "text", value: text || "" }];
  const q = query.toLowerCase();
  const lower = text.toLowerCase();
  const out = [];
  let i = 0;
  while (i < text.length) {
    const hit = lower.indexOf(q, i);
    if (hit === -1) {
      out.push({ kind: "text", value: text.slice(i) });
      break;
    }
    if (hit > i) out.push({ kind: "text", value: text.slice(i, hit) });
    out.push({ kind: "match", value: text.slice(hit, hit + q.length) });
    i = hit + q.length;
  }
  return out;
}
