import argparse
import dataclasses
import datetime
import enum
import json
import logging
import os
import pathlib
import sys
import tomllib
import typing
import urllib.parse
import urllib.request

# バージョン番号
__version__: typing.Final[str] = '3.0.0'

# 番組名をファイル名にする時に適用する変換テーブル
translate_map = str.maketrans({
    # Linux/Windows/Mac共通の禁止文字
    '/': '／',
    # Linuxの禁止文字
    '\0': '',
    # Windowsの禁止文字
    '\\': '＼',
    ':': '：',
    '*': '＊',
    '?': '？',
    '"': '”',
    '<': '＜',
    '>': '＞',
    '|': '｜',
    # 改行など
    '\r': '',
    '\n': ' ',
    '\t': ' ',
})


@dataclasses.dataclass(frozen=True)
class Program:
    """mirakcの番組情報"""
    id: int
    eventId: int
    serviceId: int
    networkId: int
    startAt: int
    duration: int
    isFree: bool
    name: str
    description: typing.Optional[str] = None
    extended: dict[str, str] = dataclasses.field(default_factory=dict[str, str])
    transportStreamId: typing.Optional[int] = None
    audio: typing.Any = None
    audios: typing.Any = None
    relatedItems: typing.Any = None
    video: typing.Any = None
    genres: typing.Any = None


@dataclasses.dataclass(frozen=True)
class Options:
    """mirakcの録画スケジュールで指定するOption"""
    contentPath: str
    priority: int
    postFilters: list[str] = dataclasses.field(default_factory=list[str])
    preFilters: list[str] = dataclasses.field(default_factory=list[str])


class State(enum.StrEnum):
    """録画状態のenum"""
    SCHEDULED = 'scheduled'
    TRACKING = 'tracking'
    RECORDING = 'recording'
    RESCHEDULING = 'rescheduling'
    FINISHED = 'finished'
    FAILED = 'failed'


@dataclasses.dataclass(frozen=True)
class Schedule:
    """mirakcの録画スケジュール"""
    state: State
    program: Program
    options: Options
    failedReason: typing.Any = None
    tags: list[str] = dataclasses.field(default_factory=list[str])


@dataclasses.dataclass(frozen=True)
class Rule:
    """設定ファイルの録画ルール"""
    keywords: list[str] = dataclasses.field(default_factory=list[str])
    excludeKeywords: list[str] = dataclasses.field(default_factory=list[str])
    serviceIds: list[int] = dataclasses.field(default_factory=list[int])
    matchName: bool = True
    matchDescription: bool = False
    matchExtended: bool = False

    def is_match(self, program: Program) -> bool:
        """番組がルールにマッチするかどうか"""
        # サービスIDが指定されていれば判定
        if len(self.serviceIds) != 0 and program.serviceId not in self.serviceIds:
            return False

        # 探す対象文字列
        target_string: list[str] = []
        if self.matchName:
            target_string.append(program.name)
        if self.matchDescription and program.description:
            target_string.append(program.description)
        if self.matchExtended:
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


@dataclasses.dataclass(frozen=True)
class Config:
    """設定ファイル"""
    apiEndpoint: str
    timezoneOffset: int = +9
    recTag: str = 'miracron'
    fileNamePattern: str = '{startAt:%Y%m%d}_{name}.m2ts'
    preFilters: list[str] = dataclasses.field(default_factory=list[str])
    postFilters: list[str] = dataclasses.field(default_factory=list[str])
    rules: list[Rule] = dataclasses.field(default_factory=list[Rule])

    @classmethod
    def load(cls, path: str):
        """設定ファイルの読み取り"""
        with open(path, 'rb') as f:
            tomlDict = tomllib.load(f)
        tomlRules = tomlDict.pop('rules')
        return cls(**tomlDict, rules=[Rule(**item) for item in tomlRules])

    def create_rec_option(self, program: Program) -> Options:
        content_path = self.fileNamePattern.format(
            startAt=datetime.datetime.fromtimestamp(
                program.startAt / 1000,
                datetime.timezone(datetime.timedelta(hours=self.timezoneOffset))
            ),
            name=program.name.translate(translate_map)
        )
        return Options(
            contentPath=content_path,
            priority=0,
            preFilters=self.preFilters,
            postFilters=self.postFilters,
        )


@dataclasses.dataclass(frozen=True)
class MirakcClient:
    """mirakcのAPIを叩くクラス"""
    apiEndpoint: str
    dryrun: bool

    def get_programs(self) -> list[Program]:
        """番組リスト取得"""
        programs_url: str = urllib.parse.urljoin(self.apiEndpoint, 'programs')
        with urllib.request.urlopen(programs_url) as res:
            jsonListPrograms: list[dict[str, typing.Any]] = json.load(res)

        # 名前がない番組を弾きつつクラスに変換
        programs: list[Program] = []
        for item in jsonListPrograms:
            if 'name' not in item:
                continue
            programs.append(Program(**item))
        return programs

    def get_schedules(self) -> list[Schedule]:
        """既存の録画スケジュール取得"""

        def _hook(dict: dict[str, typing.Any]) -> typing.Any:
            if 'startAt' in dict:
                return Program(**dict)
            elif 'contentPath' in dict:
                return Options(**dict)
            else:
                return dict

        schedules_url: str = urllib.parse.urljoin(self.apiEndpoint, 'recording/schedules')
        with urllib.request.urlopen(schedules_url) as res:
            jsonListSchedules: list[dict[str, typing.Any]] = json.load(res, object_hook=_hook)
        # クラスに変換しつつ返す
        return [Schedule(**item) for item in jsonListSchedules]

    def delete_schedule(self, program_id: int):
        """指定されたIDの録画予約を削除する"""
        if self.dryrun:
            return
        req = urllib.request.Request(
            urllib.parse.urljoin(self.apiEndpoint, f'recording/schedules/{program_id}'),
            method='DELETE',
        )
        with urllib.request.urlopen(req) as res:
            pass

    def post_schedule(self, program_id: int, tags: list[str], options: Options) -> dict[str, typing.Any]:
        """録画予約を実行する"""
        if self.dryrun:
            return {}
        data = {
            'programId': program_id,
            'options': vars(options),
            'tags': tags,
        }
        req = urllib.request.Request(
            urllib.parse.urljoin(self.apiEndpoint, 'recording/schedules'),
            data=json.dumps(data).encode('utf-8'),
            method='POST',
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req) as res:
            return json.load(res)


class Action(enum.StrEnum):
    """番組単位でどんな操作を行うかのenum"""
    ADD = enum.auto()
    UPDATE = enum.auto()
    DELETE = enum.auto()
    SKIP = enum.auto()
    NOACTION = enum.auto()


def get_argparse() -> argparse.ArgumentParser:
    """引数のパーサを作成する"""
    parser = argparse.ArgumentParser(
        prog='miracron',
        description='A script for scheduled TV recording with mirakc',
        exit_on_error=True,
    )
    # バージョン情報
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'%(prog)s {__version__}',
    )
    # 設定ファイル
    parser.add_argument(
        '--config',
        metavar='<path>',
        type=pathlib.Path,
        default=os.getenv('MIRACRON_CONFIG', './config.yml'),
        help='path to the configuration file [env: MIRACRON_CONFIG] [default: ./config.yml]',
    )
    # テスト用
    parser.add_argument(
        '--dry-run',
        dest='dryrun',
        action='store_true',
        help='no schedules will be added',
    )
    return parser


def print_log(action: Action, program_id: int, content_path: str, tags: list[str]):
    """ログを書く"""
    logging.getLogger('miracron').info(
        f'[{action.center(6, " ")}] '
        f'programId: {program_id}, '
        f'contentPath: "{content_path}", '
        f'tags: "{tags}"'
    )


def get_action(program: Program, rules: list[Rule], schedules: dict[int, Schedule], recTag: str) -> Action:
    """番組単位でどのような操作を行うか判定する"""
    # どれかの予約ルールにマッチした
    if any(rule.is_match(program) for rule in rules):
        # 既に予約されている
        if program.id in schedules:
            # 他の仕組みで予約されているか、既に録画が進んでいる
            if recTag not in schedules[program.id].tags or schedules[program.id].state != State.SCHEDULED:
                return Action.SKIP
            # miracronで既に予約されているものは更新
            else:
                return Action.UPDATE
        # 新規予約
        else:
            return Action.ADD
    # 既存の予約のうち、ルールにマッチせず・miracronで予約し・録画が始まっていないものを消す
    elif program.id in schedules and recTag in schedules[program.id].tags and schedules[program.id].state == State.SCHEDULED:
        return Action.DELETE
    # なにもしない
    else:
        return Action.NOACTION


if __name__ == '__main__':
    # TOMLパーサがpython3.11以降にしか入っていない
    if sys.version_info.major != 3 or sys.version_info.minor < 11:
        print('Please use python 3.11 or later.')
        sys.exit(-1)

    # ログ設定
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    # 引数パース
    args = get_argparse().parse_args()
    config = Config.load(args.config)
    dryrun: bool = args.dryrun

    # APIクライアント
    client = MirakcClient(apiEndpoint=config.apiEndpoint, dryrun=dryrun)

    # 番組リスト取得し現在時刻以降に絞り込む
    timezone = datetime.timezone(datetime.timedelta(hours=config.timezoneOffset))
    now_unix = int(datetime.datetime.now(timezone).timestamp() * 1000)
    programs = filter(lambda item: item.startAt >= now_unix, client.get_programs())

    # 録画予約されている番組
    schedules = {item.program.id: item for item in client.get_schedules()}

    # 録画予約のメインループ
    for program in programs:
        match get_action(program, config.rules, schedules, config.recTag):
            case Action.ADD:
                option = config.create_rec_option(program)
                print_log(Action.ADD, program.id, option.contentPath, [config.recTag])
                client.post_schedule(program.id, [config.recTag], option)
            case Action.UPDATE:
                option = config.create_rec_option(program)
                print_log(Action.UPDATE, program.id, option.contentPath, [config.recTag])
                client.delete_schedule(program.id)
                client.post_schedule(program.id, [config.recTag], option)
            case Action.DELETE:
                schedule = schedules[program.id]
                print_log(Action.DELETE, schedule.program.id,
                          schedule.options.contentPath, schedule.tags)
                client.delete_schedule(program.id)
            case Action.SKIP:
                schedule = schedules[program.id]
                print_log(Action.SKIP, schedule.program.id,
                          schedule.options.contentPath, schedule.tags)
            case Action.NOACTION:
                pass
