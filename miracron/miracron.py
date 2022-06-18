import argparse
import dataclasses
import datetime
import json
import logging
import os
import sys
import typing
import urllib.parse
import urllib.request

import yamale

VERSION_STR: typing.Final[str] = '0.1'

# 番組名をそのままディレクトリ名にする時に適用する変換テーブル
FILENAME_TRANS_MAP: dict[str, str] = {
    '/': '_',
    '\0': None,
    '\r': None,
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

# 番組情報
@dataclasses.dataclass(frozen=True)
class Program:
    id: int
    eventId: int
    serviceId: int
    transportStreamId: int
    networkId: int
    startAt: int
    duration: int
    isFree: bool
    name: str
    audio: Audio
    audios: list[Audio]
    description: str = None
    video: Video = None
    extended: dict[str, str] = dataclasses.field(default_factory=dict[str, str])
    genres: list[Genre] = dataclasses.field(default_factory=list[Genre])

def _cast_json(dict: dict[str, any]) -> any:
    if 'un1' in dict:
        return Genre(**dict)
    if 'samplingRate' in dict:
        return Audio(**dict)
    if 'resolution' in dict:
        return Video(**dict)
    if 'name' in dict:
        return Program(**dict)

    return dict

# 番組が検索条件にマッチするか
def _is_match_config(program: Program, config) -> bool:
    # 単発録画IDにマッチすれば他のルールを考慮せずTrue
    if 'oneshots' in config.keys() and program.id in config['oneshots']:
        return True
    # ルールの判定
    if 'rules' in config.keys():
        for rule in config['rules']:
            # サービスIDが指定されていれば判定
            if 'serviceIds' in rule.keys() and (program.serviceId not in rule['serviceIds']):
                continue
            # 文字列系の判定
            if ('keywords' in rule.keys() or 'excludeKeywords' in rule.keys()) and _is_match_string(program, rule):
                return True
    return False

# 番組が検索条件にマッチするか（文字列関連のみ）
def _is_match_string(program: Program, rule) -> bool:
    target_string: list[str] = []
    if rule['matchName']:
        target_string.append(program.name)
    if rule['matchDescription']:
        target_string.append(program.description)
    if rule['matchExtended']:
        target_string.extend(program.extended.keys())
        target_string.extend(program.extended.values())

    target_string = list(filter(lambda s: s != None, target_string))
    if len(target_string) == 0:
        return False

    if 'excludeKeywords' in rule.keys():
        for exclude_keyword in rule['excludeKeywords']:
            for string in target_string:
                if exclude_keyword in string:
                    return False

    if 'keywords' in rule.keys():
        for keyword in rule['keywords']:
            has_keyword = False
            for string in target_string:
                if keyword in string:
                    has_keyword = True
                    break
            if has_keyword == False:
                return False

    return True

if __name__ == '__main__':
    # 引数パース
    parser = argparse.ArgumentParser(
        description='A cron rule generator for scheduled TV recording',
        exit_on_error=True,
    )
    parser.add_argument('-V', '--version', action='version', version=f'%(prog)s {VERSION_STR}')
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
    args = parser.parse_args()

    # ログ設定
    logger = logging.getLogger('miracron')
    logger.setLevel(args.loglevel.upper())
    if args.logfile:
        file_handler = logging.FileHandler(filename = args.logfile)
        file_handler.setFormatter(logging.Formatter(fmt = '%(asctime)s [%(levelname)s] %(message)s'))
        logger.addHandler(file_handler)
    else:
        stdout_handler = logging.StreamHandler(stream = sys.stdout)
        stdout_handler.addFilter(lambda record: record.levelno <= logging.INFO)
        logger.addHandler(stdout_handler)
        stderr_handler = logging.StreamHandler(stream = sys.stderr)
        stderr_handler.addFilter(lambda record: record.levelno > logging.INFO)
        logger.addHandler(stderr_handler)

    logger.info('Start miracron.')
    logger.debug('Start loading configuration.')

    # configファイルの事前検証
    try:
        schema = yamale.make_schema(os.path.join(os.path.dirname(__file__), 'schema.yml'))
        data = yamale.make_data(args.config)
        yamale.validate(schema, data)
    except Exception as e:
        logger.error('Failed to parse configuration.')
        logger.exception(e)
        sys.exit(1)

    # config読み取り
    config = data[0][0]

    # デフォルト値の設定
    if 'recPriority' not in config.keys():
        config['recPriority'] = 2
    if 'startMarginSec' not in config.keys():
        config['startMarginSec'] = 5
    if 'recordDirectory' not in config.keys():
        config['recordDirectory'] = '/var/lib/miracron/recorded'
    if 'rules' in config.keys():
        for rule in config['rules']:
            if 'matchName' not in rule.keys():
                rule['matchName'] = True
            if 'matchDescription' not in rule.keys():
                rule['matchDescription'] = False
            if 'matchExtended' not in rule.keys():
                rule['matchExtended'] = False

    logger.debug('Loading configuration is completed. Start getting the programs.')

    # 番組表の取得
    programs_url: str = urllib.parse.urljoin(config['mirakurunUrl'], 'api/programs')
    req: urllib.request.Request = urllib.request.Request(programs_url)
    try:
        with urllib.request.urlopen(req) as res:
            programs: list[Program] = json.load(res, object_hook=_cast_json)
            filtered_programs = list(filter(lambda p: type(p) == Program, programs))
    except Exception as e:
        logger.error('Failed to get programs')
        logger.exception(e)
        sys.exit(1)

    # ルールにマッチするものに絞り込んで日付順に並び替え
    match_programs = sorted(filter(lambda p:_is_match_config(p, config), filtered_programs), key=lambda p: p.startAt)

    logger.debug('Getting programs and filtering is completed. Start generating cron rules.')

    margin_sec = datetime.timedelta(seconds = config['startMarginSec'])
    timezone = datetime.datetime.utcnow().astimezone().tzinfo
    translate_map = str.maketrans(FILENAME_TRANS_MAP)

    cron_list = []
    # cronルールの生成
    for program in match_programs:
        start_at = datetime.datetime.fromtimestamp(program.startAt / 1000, timezone)
        start_margin = start_at - margin_sec
        info_url = urllib.parse.urljoin(config['mirakurunUrl'], f"api/programs/{program.id}")
        stream_url = urllib.parse.urljoin(config['mirakurunUrl'], f"api/programs/{program.id}/stream")

        # 出力先などの準備
        dir_name = start_at.strftime("%Y%m%d") + "_" + (program.name.translate(translate_map) if program.name != None else '')
        dir_path = os.path.join(config['recordDirectory'], dir_name)
        stream_path = os.path.join(dir_path, str(program.id) + '.m2ts')
        info_path = os.path.join(dir_path, str(program.id) + '.json')
        log_path = os.path.join(dir_path, str(program.id) + '.log')

        # cron文字列
        comment_str = f"# ID:{program.id} ServiceID: {program.serviceId} StartAt: {start_at} {dir_name}"
        cron_str = f"{start_margin.minute} {start_margin.hour} {start_margin.day} {start_margin.month} * " \
            f"sleep {start_margin.second} && " \
            f"mkdir -p '{dir_path}' && " \
            f"wget -o '{log_path}' -O '{stream_path}' --header 'X-Mirakurun-Priority: {config['recPriority']}' {stream_url} && " \
            f"wget -q -O '{info_path}' {info_url}"

        logger.debug(comment_str)
        logger.debug(cron_str)
        logger.debug('#####')
        cron_list.append(comment_str)
        cron_list.append(cron_str)
        cron_list.append('#####')

    # cronルールの書き込み
    if args.outfile:
        with open(args.outfile, mode='w', encoding='utf-8') as file:
            for line in cron_list:
                file.write(line)
                file.write('\n')
    else:
        for line in cron_list:
            print(line)

    logger.info(f"Miracron completed. Scheduled program count: {len(match_programs)}")
