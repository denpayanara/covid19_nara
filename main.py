import datetime
import os
import re
import sys
import time
import unicodedata
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import requests
import tabula
import tweepy

# 和暦を西暦に変換
# https://myfrankblog.com/convert_japanese_calendar_to_western_calendar/
 
def japanese_calendar_converter(text):

    eraDict = {
        "明治": 1868,
        "大正": 1912,
        "昭和": 1926,
        "平成": 1989,
        "令和": 2019,
    }

    # 正規化
    normalized_text = unicodedata.normalize("NFKC", text)
 
    # 年月日を抽出
    pattern = r"(?P<era>{eraList})(?P<year>[0-9]{{1,2}}|元)年(?P<month>[0-9]{{1,2}})月(?P<day>[0-9]{{1,2}})日".format(eraList="|".join(eraDict.keys()))
    date = re.search(pattern, normalized_text)
 
    # 抽出できなかったら終わり
    if date is None:
        print("Cannot convert to western year")
 
    # 年を変換
    for era, startYear in eraDict.items():
        if date.group("era") == era:
            if date.group("year") == "元":
                year = eraDict[era]
            else:
                year = eraDict[era] + int(date.group("year")) - 1
    
    # date型に変換して返す
    return datetime.date(year, int(date.group("month")), int(date.group("day")))


def pdf2df(href):

    url = urljoin('https://www.pref.nara.jp', href)

    df0 = tabula.read_pdf(url, pages='1')

    df1 = pd.concat([df0[0], df0[1]], axis=0, ignore_index=True).set_index('市町村')

    df1.loc['合計'] = df1['感染者数'].sum()

    return df1


def mkdf(a_tag_list):

    df_list = []

    date_list = []

    for a_tag in a_tag_list:

        date_list.append(japanese_calendar_converter(re.search('(令和)(\d+)(年)(\d+)(月)(\d+)(日)', a_tag.text).group()).strftime('%Y/%m/%d'))
        
        data = pdf2df(a_tag.get('href'))

        df_list.append(data)

        time.sleep(3)

    df_merge = pd.merge(df_list[0], df_list[1], left_index=True, right_index=True)

    df_merge.rename(columns={'感染者数_y': '前日', '感染者数_x': '本日'}, inplace=True)

    df_merge['差分'] = df_merge['本日'] - df_merge['前日']

    df_merge.reset_index(inplace=True)
        
    return df_merge, date_list


def mkimg(df, date_list):

    img = Image.new('RGB', (1280, 720), color=(0, 0, 0))

    draw = ImageDraw.Draw(img)

    font20 = ImageFont.truetype('NotoSerifJP-Regular.otf', 20)

    for i, r in df.iterrows():

        if 0 <= i <= 15:

            draw.text((40, (i+1)*40 ), r['市町村'], font=font20, fill=(255, 255, 255))

            draw.text(
                (200, (i+1)*40 ),
                f"{'{:,}'.format(r['前日'])} → {'{:,}'.format(r['本日'])}({'{:+,}'.format(r['差分'])})",
                font=font20,
                fill=(255, 255, 255)
            )
        
        elif 32 > i > 15:

            draw.text((450, (i-15)*40 ), r['市町村'], font=font20, fill=(255, 255, 255))

            draw.text(
                (600, (i-15)*40 ),
                f"{'{:,}'.format(r['前日'])} → {'{:,}'.format(r['本日'])}({'{:+,}'.format(r['差分'])})",
                font=font20,
                fill=(255, 255, 255)
            )
        else:

            if r['市町村'] != '調査中・非公表':

                draw.text((860, (i-31)*40 ), r['市町村'], font=font20, fill=(255, 255, 255))

                draw.text(
                    (1000, (i-31)*40 ),
                    f"{'{:,}'.format(r['前日'])} → {'{:,}'.format(r['本日'])}({'{:+,}'.format(r['差分'])})",
                    font=font20,
                    fill=(255, 255, 255)
                )
                
            else:
                draw.text((860, (i-31)*40 ), r['市町村'], font=font20, fill=(255, 255, 255))

                draw.text(
                    (1095, (i-31)*40 ),
                    f"{'{:,}'.format(r['前日'])} → {'{:,}'.format(r['本日'])}({'{:+,}'.format(r['差分'])})",
                    font=font20,
                    fill=(255, 255, 255)
                )
    draw.text((860, 650 ), f'左辺:{date_list[1]} 右辺:{date_list[0]}', font=font20, fill=(255, 255, 255))

    img.save('pic.png', quality=95)


def tweet(df, date_list):

    auth = tweepy.OAuthHandler(os.environ['API_KEY'], os.environ['API_SECRET_KEY'])

    auth.set_access_token(os.environ['ACCESS_TOKEN'], os.environ['ACCESS_TOKEN_SECRET'])

    api = tweepy.API(auth)

    text_message = f'【奈良県】コロナ新規感染者数(前日比)\n\n'

    text_message += f'前日: {"{:,}".format(df.iloc[-1]["前日"])} 人\n本日: {"{:,}".format(df.iloc[-1]["本日"])} 人\n'

    text_message += f'前日比: {"{:+,}".format(df.iloc[-1]["差分"])} 人\n\n'

    text_message += f'{date_list[0]}発表分\nhttps://www.pref.nara.jp/60279.htm'

    print(text_message)

    media = api.media_upload('pic.png')

    api.update_status(status=text_message, media_ids=[media.media_id])


header = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.5 Safari/605.1.15'}

res = requests.get('https://www.pref.nara.jp/60279.htm', headers=header)

soup = BeautifulSoup(res.content, 'html.parser', from_encoding='utf-8')

# 最新と1つ前を取得
a_tag_list = soup.select('div#ContentPane > div:nth-of-type(4) div.Contents > p > a')[:2]

# 前回発表分と最新発表分を比較
with open('PreviousHrefData.text') as f:
    
    if f.read() != re.search('[^/]+$', a_tag_list[0].get('href')).group():

        print('プログラムを実行します。')

        df, date_list = mkdf(a_tag_list)

        mkimg(df, date_list)

        tweet(df, date_list)

        # 最新発表分をテキストファイルへ書き込み
        with open('PreviousHrefData.text', mode='w') as f:

            f.write(re.search('[^/]+$', a_tag_list[0].get('href')).group())

    else:
        
        print('プログラムを終了します。')
        sys.exit()
