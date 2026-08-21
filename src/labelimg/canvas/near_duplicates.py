"""Deterministic near-duplicate annotation-box detection."""

from dataclasses import dataclass


DUPLICATE_LABEL_RISK = "duplicate-label"
CATEGORY_CONFLICT = "category-conflict"


@dataclass(frozen=True)
class NearDuplicateCluster:
    """One disjoint, pairwise-close group in annotation-document order."""

    members: tuple
    risk: str
    signature: tuple

    @property
    def count(self):
        return len(self.members)

    def ordinal(self, shape):
        return self.members.index(shape) + 1


def detect_near_duplicate_clusters(shapes, edge_ratio=0.02, min_pixels=1.0):
    """Return disjoint pairwise-close clusters in document order.

    Corresponding horizontal edges use the smaller box width for tolerance;
    vertical edges use the smaller height.  Connected candidate components
    that are not complete are split greedily from their closest available
    pair, so every emitted cluster remains a strict clique and a shape occurs
    in at most one cluster.
    """
    shapes = tuple(shapes)
    shape_order = {id(shape): index for index, shape in enumerate(shapes)}
    bounds = tuple(_shape_bounds(shape) for shape in shapes)
    node_indexes = []
    node_bounds = []
    bounds_to_node = {}
    for shape_index, item in enumerate(bounds):
        node = bounds_to_node.get(item)
        if node is None:
            node = len(node_indexes)
            bounds_to_node[item] = node
            node_indexes.append([])
            node_bounds.append(item)
        node_indexes[node].append(shape_index)

    adjacency = [set() for _item in node_indexes]
    scores = {}
    for left_index in range(len(node_indexes)):
        for right_index in range(left_index + 1, len(node_indexes)):
            score = _pair_score(
                node_bounds[left_index],
                node_bounds[right_index],
                edge_ratio,
                min_pixels,
            )
            if score is None:
                continue
            adjacency[left_index].add(right_index)
            adjacency[right_index].add(left_index)
            scores[(left_index, right_index)] = score

    clusters = []
    for component in _connected_components(adjacency):
        member_count = sum(
            len(node_indexes[index]) for index in component
        )
        if member_count < 2:
            continue
        if len(component) == 1 or _is_complete(component, adjacency):
            groups = [tuple(sorted(component))]
        else:
            groups = _split_component(component, adjacency, scores)
        for nodes in groups:
            indexes = sorted(
                shape_index
                for node in nodes
                for shape_index in node_indexes[node]
            )
            members = tuple(shapes[index] for index in indexes)
            clusters.append(NearDuplicateCluster(
                members=members,
                risk=(
                    DUPLICATE_LABEL_RISK
                    if len({str(shape.label) for shape in members}) == 1
                    else CATEGORY_CONFLICT
                ),
                signature=_cluster_signature(members),
            ))

    clusters.sort(key=lambda cluster: min(
        shape_order[id(member)] for member in cluster.members
    ))
    return tuple(clusters)


def cluster_bounds(cluster):
    """Return ``left, top, right, bottom`` for a cluster union."""
    bounds = [_shape_bounds(shape) for shape in cluster.members]
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def _shape_bounds(shape):
    rect = shape.bounding_rect()
    return (
        float(rect.left()),
        float(rect.top()),
        float(rect.right()),
        float(rect.bottom()),
    )


def _pair_score(first, second, edge_ratio, min_pixels):
    first_width = first[2] - first[0]
    first_height = first[3] - first[1]
    second_width = second[2] - second[0]
    second_height = second[3] - second[1]
    if min(first_width, first_height, second_width, second_height) <= 0:
        return None
    horizontal_tolerance = max(
        float(min_pixels),
        min(first_width, second_width) * float(edge_ratio),
    )
    vertical_tolerance = max(
        float(min_pixels),
        min(first_height, second_height) * float(edge_ratio),
    )
    differences = (
        abs(first[0] - second[0]),
        abs(first[2] - second[2]),
        abs(first[1] - second[1]),
        abs(first[3] - second[3]),
    )
    if (
        differences[0] > horizontal_tolerance
        or differences[1] > horizontal_tolerance
        or differences[2] > vertical_tolerance
        or differences[3] > vertical_tolerance
    ):
        return None
    return (
        differences[0] / horizontal_tolerance
        + differences[1] / horizontal_tolerance
        + differences[2] / vertical_tolerance
        + differences[3] / vertical_tolerance
    ) / 4.0


def _connected_components(adjacency):
    unseen = set(range(len(adjacency)))
    while unseen:
        start = min(unseen)
        pending = [start]
        component = set()
        while pending:
            index = pending.pop()
            if index in component:
                continue
            component.add(index)
            unseen.discard(index)
            pending.extend(adjacency[index] - component)
        yield component


def _is_complete(component, adjacency):
    expected = len(component) - 1
    return all(
        len(adjacency[index] & component) == expected
        for index in component
    )


def _split_component(component, adjacency, scores):
    available = set(component)
    groups = []
    while True:
        pairs = [
            (scores[_pair_key(left, right)], left, right)
            for left in available
            for right in adjacency[left] & available
            if left < right
        ]
        if not pairs:
            break
        _score, left, right = min(pairs)
        clique = [left, right]
        candidates = (
            adjacency[left]
            & adjacency[right]
            & available
            - {left, right}
        )
        while candidates:
            ranked = []
            for candidate in candidates:
                mean_score = sum(
                    scores[_pair_key(candidate, member)]
                    for member in clique
                ) / len(clique)
                ranked.append((mean_score, candidate))
            _mean, candidate = min(ranked)
            clique.append(candidate)
            candidates &= adjacency[candidate]
            candidates -= set(clique)
        groups.append(tuple(sorted(clique)))
        available -= set(clique)
    return groups


def _pair_key(left, right):
    return (left, right) if left < right else (right, left)


def _cluster_signature(members):
    return tuple(
        (
            getattr(shape, "session_id", None) or id(shape),
            str(shape.label),
            tuple(
                (round(float(point.x()), 6), round(float(point.y()), 6))
                for point in shape.points
            ),
        )
        for shape in members
    )
