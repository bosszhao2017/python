# coding:utf-8

'''
@author = super_fazai
@File    : taobao_tiantiantejia_real-times_update.py
@Time    : 2018/1/2 11:42
@connect : superonesfazai@gmail.com
'''

import sys
sys.path.append('..')

from taobao_parse import TaoBaoLoginAndParse
from my_pipeline import SqlServerMyPageInfoSaveItemPipeline
from my_utils import get_shanghai_time, daemon_init

from taobao_tiantiantejia import TaoBaoTianTianTeJia
import gc
from time import sleep
import os, re, pytz, datetime
import json
from settings import IS_BACKGROUND_RUNNING, TAOBAO_REAL_TIMES_SLEEP_TIME
import datetime

def run_forever():
    #### 实时更新数据
    while True:
        tmp_sql_server = SqlServerMyPageInfoSaveItemPipeline()
        try:
            result = list(tmp_sql_server.select_taobao_tiantian_tejia_all_goods_id())
        except TypeError as e:
            print('TypeError错误, 原因数据库连接失败...(可能维护中)')
            result = None
        if result is None:
            pass
        else:
            print('------>>> 下面是数据库返回的所有符合条件的goods_id <<<------')
            print(result)
            print('--------------------------------------------------------')

            print('即将开始实时更新数据, 请耐心等待...'.center(100, '#'))
            index = 1
            tmp_taobao_tiantiantejia = TaoBaoTianTianTeJia()
            for item in result:  # 实时更新数据
                data = {}
                if index % 50 == 0:  # 每50次重连一次，避免单次长连无响应报错
                    print('正在重置，并与数据库建立新连接中...')
                    # try:
                    #     del tmp_sql_server
                    # except:
                    #     pass
                    # gc.collect()
                    tmp_sql_server = SqlServerMyPageInfoSaveItemPipeline()
                    print('与数据库的新连接成功建立...')

                if tmp_sql_server.is_connect_success:
                    tejia_end_time = item[2]
                    # print(tejia_end_time)

                    if item[1] == 1:    # 原先下架的商品，扫描到不处理
                        # tmp_sql_server.delete_taobao_tiantiantejia_expired_goods_id(goods_id=item[0])
                        # print('该商品goods_id[{0}]已售完, 删除成功!'.format(item[0]))
                        print('&&&&&& 该商品({0})原先状态为is_delete=1, 不进行实际删除操作!'.format(item[0]))
                        pass

                    elif tejia_end_time < datetime.datetime.now():
                        # 过期的不删除, 降为更新为常规爆款促销商品
                        index = update_expired_goods_to_normal_goods(goods_id=item[0], index=index, tmp_sql_server=tmp_sql_server)

                    else:
                        # 下面为天天特价商品信息更新
                        # 先检查该商品在对应的子分类中是否已经被提前下架, 并获取到该商品的上下架时间
                        # &extQuery=tagId%3A1010142     要post的数据, 此处直接用get模拟
                        tmp_url = 'https://metrocity.taobao.com/json/fantomasItems.htm?appId=9&pageSize=1000&_input_charset=utf-8&blockId={0}&extQuery=tagId%3A{1}'.format(
                            str(item[3]), item[4]
                        )
                        # print(tmp_url)

                        if index % 6 == 0:
                            tmp_taobao_tiantiantejia = TaoBaoTianTianTeJia()

                        tmp_body = tmp_taobao_tiantiantejia.get_url_body(url=tmp_url)
                        tejia_goods_list = tmp_taobao_tiantiantejia.get_tiantiantejia_goods_list(body=tmp_body)
                        # print(tejia_goods_list)
                        sleep(.45)
                        # print('111')

                        '''
                        研究发现已经上架的天天特价商品不会再被官方提前下架，所以此处什么都不做，跳过
                        '''
                        # if is_in_child_sort(tejia_goods_list, goods_id=item[0]) is False:     # 表示被官方提前下架
                        #     # tmp_sql_server.delete_taobao_tiantiantejia_expired_goods_id(goods_id=item[0])
                        #     # print('该商品goods_id[{0}]已被官方提前下架, 删除成功!'.format(item[0]))
                        #     print('222')
                        #     pass

                        # else:       # 表示商品未被提前下架
                        print('------>>>| 正在更新的goods_id为(%s) | --------->>>@ 索引值为(%d)' % (item[0], index))
                        taobao = TaoBaoLoginAndParse()
                        taobao.get_goods_data(item[0])
                        goods_data = taobao.deal_with_data(goods_id=item[0])
                        if goods_data != {}:
                            tmp_time = get_this_goods_id_tejia_time(tejia_goods_list, goods_id=item[0])
                            if tmp_time != []:
                                begin_time, end_time = tmp_time

                                goods_data['goods_id'] = item[0]
                                goods_data['schedule'] = [{
                                    'begin_time': begin_time,
                                    'end_time': end_time,
                                }]
                                goods_data['tejia_begin_time'], goods_data['tejia_end_time'] = tmp_taobao_tiantiantejia.get_tejia_begin_time_and_tejia_end_time(schedule=goods_data.get('schedule', [])[0])
                                taobao.update_taobao_tiantiantejia_table(data=goods_data, pipeline=tmp_sql_server)
                            else:
                                pass
                        else:
                            sleep(4)    # 否则休息4秒
                            pass
                        sleep(TAOBAO_REAL_TIMES_SLEEP_TIME)
                        index += 1
                        gc.collect()

                else:  # 表示返回的data值为空值
                    print('数据库连接失败，数据库可能关闭或者维护中')
                    pass
                gc.collect()
            print('全部数据更新完毕'.center(100, '#'))  # sleep(60*60)
        if get_shanghai_time().hour == 0:  # 0点以后不更新
            sleep(60 * 60 * 5.5)
        else:
            sleep(5)
        gc.collect()

def update_expired_goods_to_normal_goods(goods_id, index, tmp_sql_server):
    '''
    过期的不删除, 降为更新为常规爆款促销商品
    :param goods_id:
    :param index:
    :param tmp_sql_server:
    :return: index
    '''
    # tmp_sql_server.delete_taobao_tiantiantejia_expired_goods_id(goods_id=item[0])
    # print('该商品goods_id({0})已过期, 天天特价结束时间为 [{1}], 删除成功!'.format(item[0], item[2].strftime('%Y-%m-%d %H:%M:%S')))
    print('++++++>>>| 此为过期商品, 正在更新! |<<<++++++')
    print('------>>>| 正在更新的goods_id为(%s) | --------->>>@ 索引值为(%d)' % (goods_id, index))
    taobao = TaoBaoLoginAndParse()
    data_before = taobao.get_goods_data(goods_id)
    if data_before.get('is_delete') == 1:  # 单独处理下架状态的商品
        data_before['goods_id'] = goods_id
        data_before['schedule'] = []
        data_before['tejia_begin_time'], data_before['tejia_end_time'] = '', ''

        # print('------>>>| 爬取到的数据为: ', data_before)
        taobao.update_taobao_tiantiantejia_table(data_before, pipeline=tmp_sql_server)

        sleep(TAOBAO_REAL_TIMES_SLEEP_TIME)  # 避免服务器更新太频繁
        index += 1
        gc.collect()

        return index

    goods_data = taobao.deal_with_data(goods_id=goods_id)
    if goods_data != {}:
        goods_data['goods_id'] = goods_id
        taobao.update_expired_goods_id_taobao_tiantiantejia_table(data=goods_data, pipeline=tmp_sql_server)
    else:
        sleep(4)  # 否则休息4秒
        pass
    sleep(TAOBAO_REAL_TIMES_SLEEP_TIME)
    index += 1
    gc.collect()

    return index

def is_in_child_sort(tejia_goods_list, goods_id):
    '''
    判断该商品在对应的子分类中是否已经被提前下架
    :param tejia_goods_list: 子类的分类list  [{'goods_id': , 'start_time': , 'end_time': ,}, ...]
    :param goods_id: 商品id
    :return: True(未被提前下架) or False(被提前下架)
    '''
    tmp_list = [item.get('goods_id', '') for item in tejia_goods_list]
    if tmp_list in tmp_list:
        return True
    else:
        return False

def get_this_goods_id_tejia_time(tejia_goods_list, goods_id):
    '''
    得到该goods_id的上下架时间
    :param tejia_goods_list: 子类的分类list  [{'goods_id': , 'start_time': , 'end_time': ,}, ...]
    :param goods_id: 商品id
    :return: ['tejia_start_time', 'tejia_end_time'] or []
    '''
    for item in tejia_goods_list:
        if goods_id == item.get('goods_id', ''):
            return [item.get('start_time', ''), item.get('end_time', '')]
        else:
            pass
    return []

def main():
    '''
    这里的思想是将其转换为孤儿进程，然后在后台运行
    :return:
    '''
    print('========主函数开始========')  # 在调用daemon_init函数前是可以使用print到标准输出的，调用之后就要用把提示信息通过stdout发送到日志系统中了
    daemon_init()  # 调用之后，你的程序已经成为了一个守护进程，可以执行自己的程序入口了
    print('--->>>| 孤儿进程成功被init回收成为单独进程!')
    # time.sleep(10)  # daemon化自己的程序之后，sleep 10秒，模拟阻塞
    run_forever()

if __name__ == '__main__':
    if IS_BACKGROUND_RUNNING:
        main()
    else:
        run_forever()
