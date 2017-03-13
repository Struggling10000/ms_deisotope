from collections import deque
import numpy as np

from ms_deisotope.utils import uid


class LCMSFeature(object):
    created_at = "new"

    def __init__(self, nodes=None, adducts=None, used_as_adduct=None, feature_id=None):
        if nodes is None:
            nodes = []
        if adducts is None:
            adducts = []
        if used_as_adduct is None:
            used_as_adduct = []
        if feature_id is None:
            feature_id = uid()

        self.nodes = LCMSFeatureTreeList(nodes)
        self._total_intensity = None
        self._mz = None
        self._last_mz = 0.0
        self._most_abundant_member = 0.0
        self._retention_times = None
        self._peaks = None
        self._scan_ids = None
        self._start_time = None
        self._end_time = None
        self.adducts = adducts
        self.used_as_adduct = used_as_adduct
        self.feature_id = feature_id

    def invalidate(self):
        self._invalidate()

    def _invalidate(self):
        self._total_intensity = None
        self._last_mz = self._mz if self._mz is not None else 0.
        self._mz = None
        self._retention_times = None
        self._peaks = None
        self._scan_ids = None
        self._start_time = None
        self._end_time = None
        self._last_most_abundant_member = self._most_abundant_member
        self._most_abundant_member = None

    @property
    def most_abundant_member(self):
        if self._most_abundant_member is None:
            self._most_abundant_member = max(
                node.max_intensity() for node in self.nodes)
        return self._most_abundant_member

    def retain_most_abundant_member(self):
        self._mz = self._last_mz
        self._most_abundant_member = self._last_most_abundant_member

    @property
    def total_signal(self):
        if self._total_intensity is None:
            total = 0.
            for node in self.nodes:
                total += node.total_intensity()
            self._total_intensity = total
        return self._total_intensity

    @property
    def intensity(self):
        return self.total_signal

    @property
    def neutral_mass(self):
        return self.mz

    @property
    def mz(self):
        if self._mz is None:
            best_mz = 0
            maximum_intensity = -1
            for node in self.nodes:
                intensity = node.max_intensity()
                if intensity > maximum_intensity:
                    maximum_intensity = intensity
                    best_mz = node.mz
            assert (len(self) == 0 or best_mz != 0)
            self._last_mz = self._mz = best_mz
        return self._mz

    @property
    def retention_times(self):
        if self._retention_times is None:
            self._retention_times = np.array([node.retention_time for node in self.nodes])
        return self._retention_times

    @property
    def scan_ids(self):
        if self._scan_ids is None:
            self._scan_ids = tuple(node.scan_id for node in self.nodes)
        return self._scan_ids

    @property
    def peaks(self):
        if self._peaks is None:
            self._peaks = tuple(node.peaks for node in self.nodes)
        return self._peaks

    @property
    def start_time(self):
        if self._start_time is None:
            self._start_time = self.nodes[0].retention_time
        return self._start_time

    @property
    def end_time(self):
        if self._end_time is None:
            self._end_time = self.nodes[-1].retention_time
        return self._end_time

    def overlaps_in_time(self, interval):
        cond = ((self.start_time <= interval.start_time and self.end_time >= interval.end_time) or (
            self.start_time >= interval.start_time and self.end_time <= interval.end_time) or (
            self.start_time >= interval.start_time and self.end_time >= interval.end_time and
            self.start_time <= interval.end_time) or (
            self.start_time <= interval.start_time and self.end_time >= interval.start_time) or (
            self.start_time <= interval.end_time and self.end_time >= interval.end_time))
        return cond

    def as_arrays(self):
        rts = np.array(
            [node.retention_time for node in self.nodes], dtype=np.float64)
        signal = np.array([node.total_intensity()
                           for node in self.nodes], dtype=np.float64)
        return rts, signal

    def __len__(self):
        return len(self.nodes)

    def __repr__(self):
        return "%s(%0.4f, %0.2f, %0.2f)" % (
            self.__class__.__name__, self.mz, self.start_time, self.end_time)

    def split_sparse(self, delta_rt=1.):
        chunks = []
        current_chunk = []
        last_rt = self.nodes[0].retention_time

        for node in self.nodes:
            if (node.retention_time - last_rt) > delta_rt:
                x = self.__class__(LCMSFeatureTreeList(current_chunk))
                x.used_as_adduct = list(self.used_as_adduct)

                chunks.append(x)
                current_chunk = []

            last_rt = node.retention_time
            current_chunk.append(node)

        x = self.__class__(LCMSFeatureTreeList(current_chunk))
        x.used_as_adduct = list(self.used_as_adduct)

        chunks.append(x)
        for chunk in chunks:
            chunk.created_at = self.created_at

        for member in chunks:
            for other in chunks:
                if member == other:
                    continue
                assert not member.overlaps_in_time(other)

        return chunks

    def truncate_before(self, time):
        _, i = self.nodes.find_time(time)
        if self.nodes[i].retention_time < time:
            i += 1
        self.nodes = LCMSFeatureTreeList(self.nodes[i:])
        self._invalidate()

    def truncate_after(self, time):
        _, i = self.nodes.find_time(time)
        if self.nodes[i].retention_time < time:
            i += 1
        self.nodes = LCMSFeatureTreeList(self.nodes[:i])
        self._invalidate()

    def clone(self, deep=False, cls=None):
        if cls is None:
            cls = self.__class__
        c = cls(self.nodes.clone(deep=deep), list(self.adducts), list(self.used_as_adduct))
        c.feature_id = self.feature_id
        c.created_at = self.created_at
        return c

    def insert_node(self, node):
        self.nodes.insert_node(node)
        self._invalidate()

    def insert(self, peak, retention_time):
        self.nodes.insert(retention_time, [peak])
        self._invalidate()

    def merge(self, other):
        new = self.clone()
        for node in other.nodes:
            node = node.clone()
            new.insert_node(node)
        new.created_at = "merge"
        return new

    @property
    def apex_time(self):
        rt, intensity = self.as_arrays()
        return rt[np.argmax(intensity)]

    def __iter__(self):
        return iter(self.nodes)

    def __eq__(self, other):
        if other is None:
            return False
        if len(self) != len(other):
            return False
        else:
            if abs(self.start_time - other.start_time) > 1e-4:
                return False
            elif abs(self.end_time - other.end_time) > 1e-4:
                return False
            else:
                for a, b in zip(self, other):
                    if a != b:
                        return False
                return True

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        return hash((self.mz, self.start_time, self.end_time))

    def __getitem__(self, i):
        return self.nodes[i]


class LCMSFeatureTreeList(object):

    def __init__(self, roots=None):
        if roots is None:
            roots = []
        self.roots = list(roots)
        self._node_id_hash = None

    def _invalidate(self):
        self._node_id_hash = None

    def find_time(self, retention_time):
        if len(self.roots) == 0:
            raise ValueError()
        lo = 0
        hi = len(self.roots)
        while lo != hi:
            i = (lo + hi) / 2
            node = self.roots[i]
            if node.retention_time == retention_time:
                return node, i
            elif (hi - lo) == 1:
                return None, i
            elif node.retention_time < retention_time:
                lo = i
            elif node.retention_time > retention_time:
                hi = i

    def _build_node_id_hash(self):
        self._node_id_hash = set()
        for node in self.unspool():
            self._node_id_hash.add(node.node_id)

    @property
    def node_id_hash(self):
        if self._node_id_hash is None:
            self._build_node_id_hash()
        return self._node_id_hash

    def insert_node(self, node):
        self._invalidate()
        try:
            root, i = self.find_time(node.retention_time)
            if root is None:
                if i != 0:
                    self.roots.insert(i + 1, node)
                else:
                    slot = self.roots[i]
                    if slot.retention_time < node.retention_time:
                        i += 1
                    self.roots.insert(i, node)
            else:
                root.add(node)
            return i
        except ValueError:
            self.roots.append(node)
            return 0

    def insert(self, retention_time, peaks):
        node = LCMSFeatureTreeNode(retention_time, peaks)
        return self.insert_node(node)

    def extend(self, iterable):
        for peaks, retention_time in iterable:
            self.insert(retention_time, peaks)

    def __getitem__(self, i):
        return self.roots[i]

    def __len__(self):
        return len(self.roots)

    def __iter__(self):
        return iter(self.roots)

    def clone(self, deep=False):
        return LCMSFeatureTreeList(node.clone(deep=deep) for node in self)

    def unspool(self):
        out_queue = []
        for root in self:
            stack = [root]
            while len(stack) != 0:
                node = stack.pop()
                out_queue.append(node)
                stack.extend(node.children)
        return out_queue

    def common_nodes(self, other):
        return len(self.node_id_hash & other.node_id_hash)

    def __repr__(self):
        return "LCMSFeatureTreeList(%d nodes, %0.2f-%0.2f)" % (
            len(self), self[0].retention_time, self[-1].retention_time)


class LCMSFeatureTreeNode(object):

    __slots__ = ["retention_time", "members", "_most_abundant_member", "_mz", "node_id"]

    def __init__(self, retention_time=None, members=None):
        if members is None:
            members = []
        self.retention_time = retention_time
        self.members = members
        self._most_abundant_member = None
        self._mz = 0
        self._recalculate()
        self.node_id = uid()

    def clone(self, deep=False):
        if deep:
            peaks = [peak.clone() for peak in self.members]
        else:
            peaks = list(self.members)
        node = self.__class__(
            self.retention_time, peaks)
        node.node_id = self.node_id
        return node

    def _unspool_strip_children(self):
        node = self.__class__(
            self.retention_time, list(self.members))
        yield node

    def _calculate_most_abundant_member(self):
        if len(self.members) == 1:
            self._most_abundant_member = self.members[0]
        else:
            if len(self.members) == 0:
                self._most_abundant_member = None
            else:
                self._most_abundant_member = max(
                    self.members, key=lambda x: x.intensity)

    def _recalculate(self):
        self._calculate_most_abundant_member()
        self._mz = self._most_abundant_member.mz

    def __getstate__(self):
        return (self.retention_time, self.members, self.node_id)

    def __setstate__(self, state):
        self.retention_time, self.members, self.node_id = state
        self._recalculate()

    def __reduce__(self):
        return self.__class__, (self.retention_time, []), self.__getstate__()

    @property
    def mz(self):
        if self._mz is None:
            if self._most_abundant_member is not None:
                self._mz = self._most_abundant_member.mz
        return self._mz

    def add(self, node, recalculate=True):
        if self.node_id == node.node_id:
            raise ValueError("Duplicate Node %s" % node)
        self.members.extend(node.members)
        if recalculate:
            self._recalculate()

    def _total_intensity_members(self):
        total = 0.
        for peak in self.members:
            total += peak.intensity
        return total

    def max_intensity(self):
        return self._most_abundant_member.intensity

    def total_intensity(self):
        return self._total_intensity_members()

    def __eq__(self, other):
        return self.members == other.members

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        return hash(self.uid)

    @property
    def peaks(self):
        peaks = list(self.members)
        return peaks

    def __repr__(self):
        return "%s(%f, %0.4f %s|%d)" % (
            self.__class__.__name__,
            self.retention_time, self.peaks[0].mz, "",
            len(self.members))


class EmptyFeature(object):
    def __init__(self, mz):
        self.mz = mz
        self.start_time = 0
        self.end_time = float('inf')
        self.nodes = LCMSFeatureTreeList([])

    def __len__(self):
        return 0

    @property
    def retention_times(self):
        return np.array([])

    def __iter__(self):
        return iter([])

    def __repr__(self):
        return "EmptyFeature(%f)" % (self.mz,)


def extrapolate_time_points(features):
    start_time = max([f.start_time for f in features if f is not None])
    end_time = min([f.end_time for f in features if f is not None])

    time_points = set()
    for feature in features:
        if feature is None:
            continue
        rts = np.array(feature.retention_times)
        time_points.update(rts[(rts >= start_time) & (rts <= end_time)])
    time_points = sorted(time_points)
    return time_points


def extract_time_points(features):
    time_points = set()
    for feature in features:
        if feature is None:
            continue
        time_points.update(feature.retention_times)
    time_points = sorted(time_points)
    return time_points


def bounding_box(features, time_points=None, start_time=None, end_time=None, n_failures=25):
    if time_points is None:
        time_points = extract_time_points(features)
    n = len(features)
    if n <= 2:
        threshold = 1.0
    else:
        threshold = 0.33
    start_time = None
    end_time = None
    j = 0
    if start_time is None:
        offset_start = 0
    else:
        offset_start = binsearch(time_points, start_time)
    if end_time is None:
        offset_end = len(time_points)
    else:
        offset_end = binsearch(time_points, end_time)
    for time in time_points[offset_start:offset_end]:
        i = 0
        for feature in features:
            if feature is None:
                i += 1.
                continue
            if feature.nodes.find_time(time)[0] is not None:
                i += 1.0
        if (i / n) >= threshold:
            j = 0
            if start_time is None:
                start_time = time
        else:
            if start_time is not None:
                j += 1
                if j > n_failures:
                    end_time = time
                    break
    if end_time is None:
        end_time = time
    return start_time, end_time


class FeatureSetIterator(object):
    @staticmethod
    def extract_time_points(features, start_time, end_time):
        time_points = set()
        for feature in features:
            rts = (feature.retention_times)
            time_points.update(rts)
        time_points = sorted(time_points)
        si = binsearch(time_points, start_time)
        ei = binsearch(time_points, end_time)
        time_points = time_points[si:ei + 1]
        return time_points

    def __init__(self, features, start_time=None, end_time=None):
        self.features = features
        self.real_features = [f for f in features if f is not None and not isinstance(f, EmptyFeature)]
        self.start_time = max(
            [f.start_time for f in self.real_features]
        ) if start_time is None else start_time
        self.end_time = min(
            [f.end_time for f in self.real_features]
        ) if end_time is None else end_time
        self.time_point_queue = deque([self.start_time])
        self.last_time_seen = None

    def get_next_time(self):
        if self.time_point_queue:
            next_time = self.time_point_queue.popleft()
            return next_time
        else:
            options = set()
            for feature in self.real_features:
                _, index = feature.nodes.find_time(self.last_time_seen)
                try:
                    node = feature[index + 1]
                    node_time = node.retention_time
                    if node_time >= self.end_time:
                        continue
                    options.add(node_time)
                except IndexError:
                    continue
            if len(options) == 0:
                return None
            options = sorted(options)
            next_time = options[0]
            self.time_point_queue.extend(options[1:])
            return next_time

    @property
    def current_time(self):
        return self.last_time_seen

    def get_peaks_for_time(self, time):
        peaks = []
        for feature in self.features:
            if feature is not None:
                try:
                    node, ix = feature.nodes.find_time(time)
                except ValueError:
                    if not isinstance(feature, EmptyFeature):
                        raise
                    node = None
                if node is not None:
                    peaks.append(node.members[0])
                else:
                    peaks.append(None)
            else:
                peaks.append(None)
        return peaks

    def __next__(self):
        time = self.get_next_time()
        if time is None:
            raise StopIteration()
        self.last_time_seen = time
        peaks = self.get_peaks_for_time(time)
        return peaks

    def next(self):
        return self.__next__()

    def reset(self):
        self.time_point_queue = deque([self.start_time])
        self.last_time_seen = None

    def __iter__(self):
        return self


def binsearch(array, value):
    lo = 0
    hi = len(array)
    while hi != lo:
        mid = (hi + lo) / 2
        point = array[mid]
        if value == point:
            return mid
        elif hi - lo == 1:
            return mid
        elif point > value:
            hi = mid
        else:
            lo = mid


try:
    has_c = True
    _LCMSFeatureTreeList = LCMSFeatureTreeList
    _LCMSFeatureTreeNode = LCMSFeatureTreeNode
    _LCMSFeature = LCMSFeature
    _FeatureSetIterator = FeatureSetIterator
    _EmptyFeature = EmptyFeature
    from ms_deisotope._c.feature_map.lcms_feature import (
        LCMSFeatureTreeList,
        LCMSFeatureTreeNode,
        LCMSFeature,
        FeatureSetIterator,
        EmptyFeature,
    )
except ImportError:
    has_c = False


class NodeFeatureSetIterator(FeatureSetIterator):
    def get_peaks_for_time(self, time):
        peaks = []
        for feature in self.features:
            if feature is not None:
                try:
                    node, ix = feature.nodes.find_time(time)
                except ValueError:
                    if not isinstance(feature, EmptyFeature):
                        raise
                    node = None
                if node is not None:
                    peaks.append(node)
                else:
                    peaks.append(None)
            else:
                peaks.append(None)
        return peaks