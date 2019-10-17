import json
import random
import subprocess
import time
import traceback
import urllib

import requests

import utils
from conf.conf import V2RAY_CONFIG_LOCAL, HEALTH_POINTS, PROXIES_TEST, TEST_FILE_URL
from log import logger
from node import V2ray, Shadowsocks
from orm import session, SubscribeVmss

from fake_useragent import UserAgent

ua = UserAgent()


def get_node_by_url(url: str != ""):
    node = None
    type = ""
    try:
        if url.startswith('ss://'):  # ss node
            type = "ss"
            base64_str = url.replace('ss://', '')
            base64_str = urllib.parse.unquote(base64_str)

            origin = utils.decode(base64_str[0: base64_str.index('#')])
            remark = base64_str[base64_str.index('#') + 1:]
            security = origin[0: origin.index(':')]
            password = origin[origin.index(':') + 1: origin.index('@')]
            ipandport = origin[origin.index('@') + 1:]
            ip = ipandport[0: ipandport.index(':')]
            port = int(ipandport[ipandport.index(':') + 1:])
            ssode = Shadowsocks(ip, port, remark, security, password)
            node = ssode
        elif url.startswith('vmess://'):  # vmess
            type = "v2ray"
            base64_str = url.replace('vmess://', '')
            jsonstr = utils.decode(base64_str)

            server_node = json.loads(jsonstr)
            v2node = V2ray(server_node['add'], int(server_node['port']), server_node['ps'], 'auto', server_node['id'],
                           int(server_node['aid']), server_node['net'], server_node['type'], server_node['host'],
                           server_node['path'], server_node['tls'])
            node = v2node
        return node, type
    finally:
        return node, type


def check_by_v2ray_url(url: str) -> float:
    try:
        node, type = get_node_by_url(url)
        if node is None:
            return 0
        # subprocess.call('cp ' + V2RAY_CONFIG_LOCAL + ' ' + V2RAY_CONFIG_LOCAL + '.bak', shell=False)

        json.dump(node.formatConfig(), open(V2RAY_CONFIG_LOCAL, 'w'), indent=2)
        time.sleep(10)
        subprocess.call('systemctl restart v2ray.service', shell=True)
        # subprocess.call('supervisorctl restart v2ray_speed_measurement', shell=True)
        try:
            # output = subprocess.check_output(
            #     'curl -o /dev/null -s -w %{speed_download} -x socks://127.0.0.1:1086 ' + TEST_FILE_URL, timeout=30,
            #     shell=True)
            headers = {
                'Connection': 'close',
                "User-Agent": ua.random,
            }
            r = requests.get(TEST_FILE_URL,
                             proxies=PROXIES_TEST,
                             timeout=60 * 1000,
                             headers=headers
                             )
            if r.status_code == 200:
                speed = r.elapsed.microseconds / 1000
            else:
                speed = 0
            r.close()
        except requests.exceptions.Timeout:
            logger.warning("connect time out")
            speed = -2
        except requests.exceptions.ConnectionError:
            logger.warning("connect error")
            speed = -3
        except:
            speed = -1
            logger.error(traceback.format_exc())
        finally:
            time.sleep(10)

        logger.info("\t{}kb/s\t连接\t{}".format(speed, url))
        # subprocess.call('mv ' + V2RAY_CONFIG_LOCAL + '.bak ' + V2RAY_CONFIG_LOCAL, shell=True)
        return float(speed)
    except:
        logger.error(traceback.format_exc())
        return -1


def check_link_alive():
    while True:
        try:
            data_list = session.query(SubscribeVmss). \
                filter(SubscribeVmss.next_time < int(time.time())). \
                filter(SubscribeVmss.health_points > 0). \
                order_by(SubscribeVmss.speed.desc()). \
                all()
            # filter(SubscribeVmss.last_state.notin_(1)). \
            if len(data_list) <= 0:
                # logger.info("暂时没有待检测节点")
                time.sleep(20)
                continue
            else:
                for i, data in enumerate(data_list):
                    try:
                        speed = check_by_v2ray_url(data.url)
                        state = 0
                        if speed < 0:
                            state = int(-1 * speed)

                        if speed > 0:
                            session.query(SubscribeVmss).filter(SubscribeVmss.id == data.id).update({
                                SubscribeVmss.speed: speed,
                                SubscribeVmss.health_points: HEALTH_POINTS if data.health_points < HEALTH_POINTS else data.health_points + 1,
                                SubscribeVmss.next_time: int(random.uniform(0.5, 1.5) * data.interval) + int(
                                    time.time()),
                                SubscribeVmss.updated_at: int(time.time()),
                                SubscribeVmss.last_state: state,
                            })
                        elif speed == 0 or (state != 0 and speed < 0):
                            session.query(SubscribeVmss).filter(SubscribeVmss.id == data.id).update({
                                SubscribeVmss.health_points: data.health_points - 1,
                                SubscribeVmss.next_time: int(random.uniform(0.5, 1.5) * data.interval) + int(
                                    time.time()),
                                SubscribeVmss.updated_at: int(time.time()),
                                SubscribeVmss.last_state: state,
                            })
                        else:
                            session.query(SubscribeVmss).filter(SubscribeVmss.id == data.id).update({
                                SubscribeVmss.speed: speed,
                                SubscribeVmss.health_points: -1,
                                SubscribeVmss.updated_at: int(time.time()),
                                SubscribeVmss.last_state: state,
                            })
                        session.commit()
                    except:
                        logger.error(traceback.format_exc())
                    finally:
                        time.sleep(5)
                        # logger.info("第{}个节点监测完成".format(i+1))
                logger.info("{}个节点检测完成".format(i + 1))
        except:
            logger.error(traceback.format_exc())
            time.sleep(10)
        finally:
            # logger.info("节点检测完成")
            time.sleep(10)
