import datetime
import os
import requests
import pathlib
import logging
import gzip
import itertools
from functools import partial
import multiprocessing

from .constants import STATCAST_PBP_DAILY_URL_FORMAT

logger = logging.getLogger(__name__)


def _download_csv(url):
    logger.info("downloading file from {}".format(url))
    response = requests.get(url, stream=True)
    if response.status_code != 200:
        logger.info("there was a download error code={}", response.status_code)
        raise FileNotFoundError
    it = response.iter_lines()
    return list(it)


def _save(lines, file_name, output_path):
    output_file_path = os.path.join(output_path, file_name)
    output_payload = "\n".join(",".join(line) for line in lines)
    logger.info("saving file to {}".format(output_file_path))
    with gzip.open(output_file_path, "wb") as fh:
        fh.write(bytes(output_payload, encoding="utf-8"))


def _update_file(
    url,
    output_root,
    output_filename=None,
    rows_filter=None,
    overwrite=False,
):
    output_filename = output_filename or ".".join(os.path.basename(url), "gz")
    output_path = os.path.join(output_root, "statcast")
    os.makedirs(output_path, exist_ok=True)

    output_file_path = os.path.join(output_path, output_filename)
    if os.path.exists(output_file_path):
        if not overwrite:
            logger.info("file %s exists, not overwriting", output_file_path)
            return
        else:
            logger.warning("file %s exists, but overwriting", output_file_path)

    lines = _download_csv(url)
    if rows_filter is not None:
        lines = rows_filter(lines)

    _save(lines, output_filename, output_path)


def _validate_path(output_root):
    output_root = output_root or pathlib.Path(__file__).parent.parent.parent / "assets"
    if not os.path.exists(output_root):
        raise ValueError(f"Path {output_root} does not exist")
    if not os.path.isdir(output_root):
        raise ValueError(f"Path {output_root} must be a directory")



def _pool_do_update(overwrite=False, season_stats=None):
    start_date, player_type, output_root = season_stats

    url_formatter = STATCAST_PBP_DAILY_URL_FORMAT
    url = url_formatter.format(
        **{
            "player_type": player_type,
            "season": start_date[0:4],
            "start_date": start_date,
            "end_date": start_date
        }
    )

    logger.debug("url %s", url)
    _update_file(
        url,
        output_root,
        f"sc_{player_type}_{start_date}.csv.gz",
        rows_filter=None,
        overwrite=overwrite,
    )



def _update(
    output_root=None, min_date=None, max_date=None, num_threads=2, overwrite=False
):
    today = datetime.date.today()
    min_date = min_date or (today - datetime.timedelta(1)).strftime("%Y-%m-%d")
    max_date = max_date or today.strftime("%Y-%m-%d")

    # the case where date is a year string
    if len(min_date) == 4:
        min_date += "-03-15"

    if len(max_date) == 4:
        max_date += "-11-15"

    output_root = (
        output_root or pathlib.Path(__file__).absolute().parent.parent / "assets"
    )
    logger.debug("output root is %s", output_root)
    _validate_path(output_root)


    min_date_obj = datetime.datetime.strptime(min_date, "%Y-%m-%d")
    max_date_obj = datetime.datetime.strptime(max_date, "%Y-%m-%d")
    dt_count = (max_date_obj-min_date_obj).days

    date_obj_seq = [min_date_obj + datetime.timedelta(dt) for dt in range(dt_count+1)]
    pbp_dates = [datetime.datetime.strftime(d) for d in date_obj_seq]
    stat_names = ["batting", "pitching"]

    season_stats_it = itertools.product(pbp_dates, stat_names, [output_root])
    func = partial(_pool_do_update, overwrite)
    logger.debug("Starting downloads with %d threads", num_threads)
    # TODO: consider using a concurrent.futures.ThreadPoolExecutor instead
    with multiprocessing.Pool(num_threads) as mp:
        mp.map(func, season_stats_it)
