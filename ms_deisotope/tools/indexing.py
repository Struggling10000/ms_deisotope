import os
import math

from collections import Counter

import ms_deisotope

import click

from ms_deisotope.feature_map import quick_index
from ms_deisotope.feature_map import scan_interval_tree

from ms_deisotope.clustering.scan_clustering import (
    iterative_clustering, ScanClusterWriter)

from ms_deisotope.data_source import _compression
from ms_deisotope.data_source.scan import RandomAccessScanSource
from ms_deisotope.data_source.metadata.file_information import SourceFile

from ms_deisotope.output import ProcessedMzMLDeserializer

from ms_deisotope.tools import conversion
from ms_deisotope.tools.utils import processes_option


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=CONTEXT_SETTINGS)
def cli():
    pass


@cli.command("describe", short_help=("Produce a minimal textual description"
                                     " of a mass spectrometry data file"))
@click.argument('path', type=click.Path(exists=True))
def describe(path):
    click.echo("Describing \"%s\"" % (path,))
    try:
        sf = SourceFile.from_path(path)
    except IOError:
        click.echo("Could not open", err=True)
    if sf.file_format is None:
        click.echo("It doesn't appear to be a mass spectrometry data file")
        return -1
    click.echo("File Format: %s" % (sf.file_format, ))
    click.echo("ID Format: %s" % (sf.id_format, ))
    reader = ms_deisotope.MSFileLoader(path)
    if isinstance(reader, RandomAccessScanSource):
        click.echo("Format Supports Random Access: True")
        first_scan = reader[0]
        last_scan = reader[-1]
        click.echo("First Scan: %s at %0.3f minutes" % (first_scan.id, first_scan.scan_time))
        click.echo("Last Scan: %s at %0.3f minutes" % (last_scan.id, last_scan.scan_time))
    else:
        click.echo("Format Supports Random Access: False")
    try:
        finfo = reader.file_description()
        click.echo("Contents:")
        for key in finfo.contents:
            click.echo("    %s" % (key, ))
    except AttributeError:
        pass
    index_file_name = quick_index.ExtendedScanIndex.index_file_name(path)
    # Extra introspection if the extended index is available
    if os.path.exists(index_file_name):
        with open(index_file_name, 'rt') as fh:
            index = quick_index.ExtendedScanIndex.deserialize(fh)
        ms1_scans = len(index.ms1_ids)
        msn_scans = len(index.msn_ids)
        click.echo("MS1 Scans: %d" % (ms1_scans, ))
        click.echo("MSn Scans: %d" % (msn_scans, ))
        n_defaulted = 0
        n_orphan = 0

        charges = Counter()
        first_msn = float('inf')
        last_msn = 0
        for scan_info in index.msn_ids.values():
            n_defaulted += scan_info.get('defaulted', False)
            n_orphan += scan_info.get('orphan', False)
            charges[scan_info['charge']] += 1
            rt = scan_info['scan_time']
            if rt < first_msn:
                first_msn = rt
            if rt > last_msn:
                last_msn = rt
        click.echo("First MSn Scan: %0.3f minutes" % (first_msn,))
        click.echo("Last MSn Scan: %0.3f minutes" % (last_msn,))
        for charge, count in sorted(charges.items()):
            if not isinstance(charge, int):
                continue
            click.echo("Precursors with Charge State %d: %d" % (charge, count))
        if n_defaulted > 0:
            click.echo("Defaulted MSn Scans: %d" % (n_defaulted,))
        if n_orphan > 0:
            click.echo("Orphan MSn Scans: %d" % (n_orphan,))


@cli.command("byte-index", short_help='Build an external byte offset index for a mass spectrometry data file')
@click.argument('paths', type=click.Path(exists=True), nargs=-1)
def byte_index(paths):
    for path in paths:
        reader = ms_deisotope.MSFileLoader(path, use_index=False)
        try:
            fn = reader.prebuild_byte_offset_file
        except AttributeError:
            click.echo("\"%s\" does not support pre-indexing byte offsets" % (path,))
            return
        fn(path)


@cli.command("metadata-index", short_help='Build an external scan metadata index for a mass spectrometry data file')
@click.argument('paths', type=click.Path(exists=True), nargs=-1)
@processes_option
def metadata_index(paths, processes=4):
    for path in paths:
        reader = ms_deisotope.MSFileLoader(path)
        try:
            fn = reader.prebuild_byte_offset_file
            if not reader.source._check_has_byte_offset_file():
                fn(path)
        except AttributeError:
            pass
        index, interval_tree = quick_index.index(reader, processes)
        name = path
        index_file_name = index.index_file_name(name)
        with open(index_file_name, 'w') as fh:
            index.serialize(fh)


def partial_ms_file_iterator(reader, start, end):
    for scan_bunch in reader.start_from_scan(index=start):
        if scan_bunch.precursor.index > end:
            break
        yield scan_bunch


class MSMSIntervalTask(object):
    def __init__(self, time_radius, mz_lower, mz_higher):
        self.time_radius = time_radius
        self.mz_lower = mz_lower
        self.mz_higher = mz_higher

    def __call__(self, payload):
        reader, start, end = payload
        iterator = partial_ms_file_iterator(reader, start, end)
        intervals = scan_interval_tree.extract_intervals(
            iterator, time_radius=self.time_radius,
            mz_lower=self.mz_lower, mz_higher=self.mz_higher)
        return intervals


@cli.command("msms-intervals", short_help=(
    'Build an interval tree over precursor isolation events in time and m/z space'))
@click.argument('paths', type=click.Path(exists=True), nargs=-1)
@click.option("-o", "--output", type=click.Path(writable=True, file_okay=True, dir_okay=False), required=False)
@processes_option
def msms_intervals(paths, processes=4, time_radius=5, mz_lower=2., mz_higher=3., output=None):
    interval_extraction = MSMSIntervalTask(time_radius, mz_lower, mz_higher)
    interval_set = []
    total_work_items = len(paths) * processes * 4

    def run():
        for path in paths:
            reader = ms_deisotope.MSFileLoader(path)
            chunk_out_of_order = quick_index.run_task_in_chunks(
                reader, processes, processes * 4, task=interval_extraction)
            for chunk in chunk_out_of_order:
                interval_set.extend(chunk)
                yield 0
    work_iterator = run()
    with click.progressbar(work_iterator, length=total_work_items, label='Extracting Intervals') as g:
        for _ in g:
            pass
    tree = scan_interval_tree.ScanIntervalTree(scan_interval_tree.make_rt_tree(interval_set))
    if output is not None:
        with open(output, 'wt') as fh:
            tree.serialize(fh)
    else:
        stream = click.get_text_stream('stdout')
        tree.serialize(stream)
        stream.flush()


def _ensure_metadata_index(path):
    reader = ms_deisotope.MSFileLoader(path)
    name = path
    index_file_name = quick_index.ExtendedScanIndex.index_file_name(name)
    if not os.path.exists(index_file_name):
        click.secho("Building Index", fg='yellow', err=True)
        index = quick_index.ExtendedScanIndex()
        reader.reset()
        for bunch in reader:
            index.add_scan_bunch(bunch)
        reader.reset()
        with open(index_file_name, 'w') as fh:
            index.serialize(fh)
    else:
        with open(index_file_name, 'rt') as fh:
            index = quick_index.ExtendedScanIndex.deserialize(fh)
    return reader, index


@cli.command("charge-states", short_help='Count the different precursor charge states in a mass spectrometry data file')
@click.argument("path", type=click.Path(exists=True))
def charge_states(path):
    reader, index = _ensure_metadata_index(path)

    charges = Counter()
    for msn_id, msn_info in index.msn_ids.items():
        charges[msn_info.charge] += 1
    for charge in sorted(charges, key=abs):
        click.echo("%d: %d" % (charge, charges[charge]))


def binsearch(array, x):
    n = len(array)
    lo = 0
    hi = n

    while hi != lo:
        mid = (hi + lo) / 2
        y = array[mid][0]
        err = y - x
        if hi - lo == 1:
            return mid
        elif err > 0:
            hi = mid
        else:
            lo = mid
    return


@cli.command("precursor-clustering", short_help='Cluster precursor masses in a mass spectrometry data file')
@click.argument("path", type=click.Path(exists=True))
def precursor_clustering(path, grouping_error=2e-5):
    reader, index = _ensure_metadata_index(path)
    points = []
    for msn_id, msn_info in index.msn_ids.items():
        points.append((msn_info.neutral_mass, msn_info.intensity))
    points.sort(key=lambda x: x[1], reverse=1)
    centroids = []
    if len(points) == 0:
        click.secho("No MS/MS detected", fg='yellow', err=True)
        return

    for point in points:
        if len(centroids) == 0:
            centroids.append((point[0], [point]))
            continue
        i = binsearch(centroids, point[0])
        centroid = centroids[i]
        err = (centroid[0] - point[0]) / point[0]
        if abs(err) < grouping_error:
            centroid[1].append(point)
        else:
            if err < 0:
                i += 1
            centroids.insert(i, (point[0], [point]))
    acc = 0
    nt = 0
    for centroid, obs in centroids:
        n = len(obs)
        if n == 1:
            continue
        mean = sum(p[0] for p in obs) / n
        var = sum([(p[0] - mean) ** 2 for p in obs]) / (n - 1)
        acc += (var * (n - 1))
        nt += (n - 1)
    for centroid, obs in centroids:
        click.echo("%f: %d" % (centroid, len(obs)))
    click.echo("MS/MS Precursor Mass Std. Dev.: %f Da" % (math.sqrt(acc / nt),))


@cli.command("spectrum-clustering", short_help=("Cluster MSn spectra in a mass spectrometry data file using"
                                                " cosine similarity"))
@click.argument('paths', type=click.Path(exists=True), nargs=-1)
@click.option("-m", "--precursor-error-tolerance", type=float, default=1e-5)
@click.option("-t", "--similarity-threshold", "similarity_thresholds", multiple=True, type=float)
@click.option("-o", "--output", "output_path", type=click.Path(writable=True, file_okay=True, dir_okay=False),
              required=False)
@click.option("-D", "--deconvoluted", is_flag=True, default=False, help=(
    "Whether to assume the spectrum is deconvoluted or not"))
def spectrum_clustering(paths, precursor_error_tolerance=1e-5, similarity_thresholds=None, output_path=None,
                        deconvoluted=False):
    if not similarity_thresholds:
        similarity_thresholds = [0.1, 0.4, 0.7]
    else:
        similarity_thresholds = sorted(similarity_thresholds)
    if output_path is None:
        output_path = "-"
    msn_scans = []
    n_spectra = 0

    with click.progressbar(paths, label="Indexing", item_show_func=str) as bar:
        key_seqs = []
        for path in bar:
            if deconvoluted:
                reader = ProcessedMzMLDeserializer(path)
                index = reader.extended_index
            else:
                reader, index = _ensure_metadata_index(path)
            key_seqs.append((reader, index))
            n_spectra += len(index.msn_ids)

    with click.progressbar(label="Loading Spectra", length=n_spectra,
                           item_show_func=str) as bar:
        for reader, index in key_seqs:
            for i in index.msn_ids:
                bar.current_item = i
                bar.update(1)
                msn_scans.append(reader.get_scan_by_id(i).pick_peaks())
    clusters = iterative_clustering(
        msn_scans, precursor_error_tolerance, similarity_thresholds)
    with click.open_file(output_path, mode='w') as outfh:
        writer = ScanClusterWriter(outfh)
        for cluster in clusters:
            writer.save(cluster)


if _compression.has_idzip:

    @cli.command("idzip", short_help='Compress a file with idzip, a gzip-compatible format with random access support')
    @click.argument('path', type=str)
    @click.option("-o", "--output", type=click.Path(writable=True, file_okay=True, dir_okay=False), required=False)
    def idzip_compression(path, output):
        if output is None:
            output = '-'
        with click.open_file(output, mode='wb') as outfh:
            writer = _compression.GzipFile(fileobj=outfh, mode='wb')
            with click.open_file(path, 'rb') as infh:
                buffer_size = 2 ** 28
                chunk = infh.read(buffer_size)
                while chunk:
                    writer.write(chunk)
                    chunk = infh.read(buffer_size)
            writer.close()


try:
    for name, command in conversion.ms_conversion.commands.items():
        cli.add_command(command, name)
except Exception as e:
    click.secho("%r occurred while loading conversion tools" % (e, ), err=True, fg='yellow')

main = cli.main

if __name__ == '__main__':
    main()
