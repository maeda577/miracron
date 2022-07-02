###################
Install
###################

::

    pip install miracron

###################
Usage
###################
*******************
Command Line
*******************

::

    $ miracron --help
    usage: miracron [-h] [-V] [-c <config>] [-l {CRITICAL,ERROR,WARNING,INFO,DEBUG}] [-L <logfile>] [-o <outfile>]

    A cron rule generator for scheduled TV recording

    options:
    -h, --help            show this help message and exit
    -V, --version         show program's version number and exit
    -c <config>, --config <config>
                            path to a configuration file [env: MIRACRON_CONFIG] [default: /etc/miracron/config.yml]
    -l {CRITICAL,ERROR,WARNING,INFO,DEBUG}, --loglevel {CRITICAL,ERROR,WARNING,INFO,DEBUG}
                            the threshold of logging level [env: MIRACRON_LOGLEVEL] [default: WARNING]
    -L <logfile>, --logfile <logfile>
                            path to logfile [default: stdout and stderr]
    -o <outfile>, --outfile <outfile>
                            path to output cron rules [default: stdout]

*******************
Library
*******************

Please refer `start_miracron_cli <https://github.com/maeda577/miracron/blob/main/miracron/miracron.py>`_ method.

###################
Configuration file
###################

Please refer `configuration sample <https://github.com/maeda577/miracron/blob/main/config-sample.yml>`_.
