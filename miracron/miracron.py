import argparse
import collections.abc
import dataclasses
import datetime
import json
import logging
import os
import pathlib
import sys
import typing
import urllib.parse
import urllib.request

import pydantic
import yaml

__version__: typing.Final[str] = '0.4.1'

# 番組名をそのままディレクトリ名にする時に適用する変換テーブル
FILENAME_TRANS_MAP: dict[str, str] = {
    '/': '_',
    '\0': '',
    '\r': '',
    '\n': ' ',
    '\'': '_',
    '#': '_',
}

@dataclasses.dataclass(frozen=True)
class Video:
    type: str
    resolution: str
    streamContent: int
    componentType: int

@dataclasses.dataclass(frozen=True)
class Audio:
    componentType: int
    isMain: bool
    samplingRate: int
    langs: list[str]

@dataclasses.dataclass(frozen=True)
class Genre:
    lv1: int
    lv2: int
    un1: int
    un2: int

# 番組情報 不正な型が入ってきても検索に引っかからないだけなのでdataclassを使う pydanticを使った結果落ちて録画失敗する方が辛い
@dataclasses.dataclass(frozen=True)
class Program:
    id: int
    eventId: int
    serviceId: int
    transportStreamId: int
    networkId: int
    startAt: datetime.datetime
    duration: int
    isFree: bool
    name: str
    audio: Audio
    audios: list[Audio]
    video: typing.Optional[Video] = None
    description: typing.Optional[str] = None
    extended: dict[str, str] = dataclasses.field(default_factory=dict[str, str])
    genres: list[Genre] = dataclasses.field(default_factory=list[Genre])

class Rule(pydantic.BaseModel, extra=pydantic.Extra.forbid):
    keywords: list[str] = []
    excludeKeywords: list[str] = []
    serviceIds: list[int] = []
    weekdays: list[int] = []
    matchName: bool = True
    matchDescription: bool = False
    matchExtended: bool = False

    def is_match(self, program: Program) -> bool:
        # サービスIDが指定されていれば判定
        if len(self.serviceIds) != 0 and program.serviceId not in self.serviceIds:
            return False
        # 曜日が指定されていれば判定
        if len(self.weekdays) != 0 and program.startAt.weekday() not in self.weekdays:
            return False

        # 探す対象文字列
        target_string: list[str] = []
        if self.matchName:
            target_string.append(program.name)
        if self.matchDescription and program.description:
            target_string.append(program.description)
        if self.matchExtended:
            target_string.extend(program.extended.keys())
            target_string.extend(program.extended.values())

        # 探す対象文字列がそもそも無ければFalse
        if len(target_string) == 0:
            return False

        # 除外キーワードが対象のどこかに1度でも出たらFalse
        for exclude_keyword in self.excludeKeywords:
            if any((exclude_keyword in string) for string in target_string):
                return False

        # 対象キーワードが対象のどこにも出てこなかったらFalse (対象キーワードはAND検索する)
        for keyword in self.keywords:
            if not any((keyword in string) for string in target_string):
                return False
        # 全て通過すればTrue
        return True

class CronConfig(pydantic.BaseModel, extra=pydantic.Extra.forbid):
    recPriority: int = 2
    startMarginSec: int = 5
    recordDirectory: pathlib.Path = pathlib.Path('/var/lib/miracron/recorded')

# 設定 厳密に入力値を検証したいのでpydanticを使う
class Config(pydantic.BaseModel, extra=pydantic.Extra.forbid):
    mirakurunUrl: pydantic.AnyHttpUrl
    timezoneDelta: datetime.timedelta = datetime.timedelta(hours=9)
    cron: CronConfig = CronConfig()
    rules: list[Rule] = []
    oneshots: list[int] = []

# 番組情報の読み込み
def get_programs(mirakurun_baseurl: str, timezone: datetime.tzinfo = datetime.timezone(datetime.timedelta(hours=9))) -> list[Program]:
    """
    Get mirakurun programs. Exclude programs without name. Default timezone is +09:00.
    """
    programs_url: str = urllib.parse.urljoin(mirakurun_baseurl, 'api/programs')

    def _cast_json(dict: dict[str, typing.Any]) -> typing.Any:
        if 'un1' in dict:
            return Genre(**dict)
        if 'samplingRate' in dict:
            return Audio(**dict)
        if 'resolution' in dict:
            return Video(**dict)
        if 'name' in dict:
            start_timestamp: int = typing.cast(int, dict.pop('startAt'))
            start_at: datetime.datetime = datetime.datetime.fromtimestamp(start_timestamp / 1000, timezone)
            return Program(**dict, startAt=start_at)
        return dict

    req: urllib.request.Request = urllib.request.Request(programs_url)
    with urllib.request.urlopen(req) as res:
        programs: list[Program] = json.load(res, object_hook=_cast_json)
    # nameが入っていないものはProgramと判定されないのでここで落とされる
    return list(filter(lambda p: type(p) == Program, programs))

# 引数のパーサ
def get_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='A cron rule generator for scheduled TV recording with mirakc/Mirakurun',
        exit_on_error=True,
    )
    parser.add_argument('-V', '--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument(
        '-c', '--config',
        metavar='<config>',
        default=os.getenv('MIRACRON_CONFIG', '/etc/miracron/config.yml'),
        help='path to a configuration file [env: MIRACRON_CONFIG] [default: /etc/miracron/config.yml]'
    )
    parser.add_argument(
        '-l', '--loglevel',
        choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'],
        default=os.getenv('MIRACRON_LOGLEVEL', 'WARNING'),
        help='the threshold of logging level [env: MIRACRON_LOGLEVEL] [default: WARNING]'
    )
    parser.add_argument(
        '-L', '--logfile',
        metavar='<logfile>',
        default=os.getenv('MIRACRON_LOGFILE'),
        help='path to logfile [default: stdout and stderr]'
    )
    parser.add_argument(
        '-o', '--outfile',
        metavar='<outfile>',
        default=os.getenv('MIRACRON_OUTFILE'),
        help='path to output cron rules [default: stdout]'
    )
    return parser

# ロガーの取得
def get_logger(loglevel: str, logpath: typing.Optional[str]) -> logging.Logger:
    logger: logging.Logger = logging.getLogger('miracron')
    logger.setLevel(loglevel.upper())
    if logpath:
        file_handler: logging.FileHandler = logging.FileHandler(filename = logpath)
        file_handler.setFormatter(logging.Formatter(fmt = '%(asctime)s [%(levelname)s] %(message)s'))
        logger.addHandler(file_handler)
    else:
        stdout_handler: logging.StreamHandler = logging.StreamHandler(stream = sys.stdout)
        stdout_handler.addFilter(lambda record: record.levelno <= logging.INFO)
        logger.addHandler(stdout_handler)
        stderr_handler: logging.StreamHandler = logging.StreamHandler(stream = sys.stderr)
        stderr_handler.addFilter(lambda record: record.levelno > logging.INFO)
        logger.addHandler(stderr_handler)
    return logger

# configのyamlファイル読み込み
def load_config(filepath: str) -> Config:
    """
    Load miracron config yaml.
    """
    with open(filepath) as file:
        conf_yaml: typing.Any = yaml.safe_load(file)
    if type(conf_yaml) != dict:
        raise ValueError('Invalid config file')

    return Config(**conf_yaml)

# 検索条件にマッチする番組に絞り込み
def filter_programs(programs: typing.Iterable[Program], rules: list[Rule], oneshots: list[int]) -> collections.abc.Generator[Program, None, None]:
    for program in programs:
        # 単発録画IDにマッチすれば他のルールを考慮せずreturn
        if program.id in oneshots:
            yield program
        # ルールの判定
        for rule in rules:
            if rule.is_match(program):
                yield program

def to_cron_commentstr(program: Program) -> str:
    return f"# ID:{program.id} ServiceID: {program.serviceId} StartAt: {program.startAt}"

def to_cron_str(program: Program, cronConfig: CronConfig, mirakurun_baseurl: str) -> str:
    start_margin: datetime.datetime = program.startAt - datetime.timedelta(seconds = cronConfig.startMarginSec)
    info_url: str = urllib.parse.urljoin(mirakurun_baseurl, f"api/programs/{program.id}")
    stream_url: str = urllib.parse.urljoin(mirakurun_baseurl, f"api/programs/{program.id}/stream")

    # 出力先などの準備
    translate_map: dict[int, str] = str.maketrans(FILENAME_TRANS_MAP)
    dir_name: str = program.startAt.strftime("%Y%m%d") + "_" + program.name.translate(translate_map)
    dir_path: str = os.path.join(cronConfig.recordDirectory, dir_name)
    stream_path: str = os.path.join(dir_path, str(program.id) + '.m2ts')
    info_path: str = os.path.join(dir_path, str(program.id) + '.json')
    log_path: str = os.path.join(dir_path, str(program.id) + '.log')

    # cron文字列
    return f"{start_margin.minute} {start_margin.hour} {start_margin.day} {start_margin.month} * " \
        f"sleep {start_margin.second} && " \
        f"mkdir -p '{dir_path}' && " \
        f"wget -o '{log_path}' -O '{stream_path}' --header 'X-Mirakurun-Priority: {cronConfig.recPriority}' {stream_url} && " \
        f"wget -q -O '{info_path}' {info_url}"

def start_miracron_cli():
    # 引数パース
    args: argparse.Namespace = get_argparse().parse_args()

    # ログ設定
    logger: logging.Logger = get_logger(args.loglevel, args.logfile)

    logger.info('Start miracron.')
    logger.debug('Start loading configuration.')

    # configファイルの事前検証
    try:
        config: Config = load_config(args.config)
    except Exception as e:
        logger.error('Failed to parse configuration.')
        logger.exception(e)
        sys.exit(1)

    logger.debug('Loading configuration is completed. Start getting the programs.')

    # 番組表の取得
    try:
        programs: list[Program] = get_programs(config.mirakurunUrl, datetime.timezone(config.timezoneDelta))
    except Exception as e:
        logger.error('Failed to get programs')
        logger.exception(e)
        sys.exit(1)

    # ルールにマッチするものに絞り込んで重複除去
    match_programs_dict: dict[int, Program] = { prg.id : prg for prg in filter_programs(programs, config.rules, config.oneshots) }
    # 日付順に並び替え
    match_programs: list[Program] = sorted(match_programs_dict.values(), key=lambda p: p.startAt)

    logger.debug('Getting programs and filtering is completed. Start generating cron rules.')

    # cronルールの書き込み
    if args.outfile:
        with open(args.outfile, mode='w', encoding='utf-8') as file:
            for program in match_programs:
                file.write(to_cron_commentstr(program) + '\n')
                file.write(to_cron_str(program, config.cron, config.mirakurunUrl) + '\n')
                file.write('#####\n')
    else:
        for program in match_programs:
            print(to_cron_commentstr(program))
            print(to_cron_str(program, config.cron, config.mirakurunUrl))
            print('#####')

    logger.info(f"Miracron completed. Scheduled program count: {len(match_programs)}")

if __name__ == '__main__':
    start_miracron_cli()
