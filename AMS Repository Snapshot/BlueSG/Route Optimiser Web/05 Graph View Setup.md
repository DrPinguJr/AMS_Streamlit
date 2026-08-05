---
title: Route Optimiser graph view setup
tags: [bluesg, route-optimiser, graph-help]
---

# Graph View setup

Bridge: [[00 Route Optimiser Mega Web]].

## Best focused view

Open this note or the mega-web note, then choose **Open local graph**. Set link depth to 4 or 5. This removes unrelated repository nodes while keeping the Route Optimiser dependency mesh.

For Global Graph, use this search filter:

```text
path:"AMS Repository Snapshot/BlueSG/Route Optimiser Web"
```

## Suggested color groups

Add Graph groups in this order:

| Query | Cluster |
|---|---|
| `tag:#graph-hub OR tag:#graph-gateway` | bridges and gateways |
| `tag:#input OR tag:#canonical-data OR tag:#identity` | job ingestion |
| `tag:#roster OR tag:#streamlit-state` | rider/workflow state |
| `tag:#time OR tag:#time-constraints` | operation timing |
| `tag:#v2` | V2 solver |
| `tag:#v1 OR tag:#compatibility` | V1/shared backend |
| `tag:#onemap OR tag:#cache OR tag:#travel-quality` | provider/cache |
| `tag:#planner` | Route Planner |
| `tag:#cloud OR tag:#deployment` | Cloud/runtime |
| `tag:#tests OR tag:#acceptance OR tag:#change-management` | contracts/change |

## Display suggestions

- turn on arrows to see dependency direction where supported;
- raise link thickness slightly;
- keep orphan and attachment display off;
- start with depth 4, then use depth 2 for a specific node;
- search a filename such as “Beam Search” or “Planner” to isolate a cluster.

The main navigation edges are [[01 Operator Journey]], [[02 Runtime Dependency Spine]], [[03 Data Lineage]], and [[91 Change Impact Routes]].

