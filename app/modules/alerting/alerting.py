import json

import pika

import modules.db.sql as sql
import modules.roxywi.common as roxywi_common


def send_message_to_rabbit(message: str, **kwargs) -> None:
	rabbit_user = sql.get_setting('rabbitmq_user')
	rabbit_password = sql.get_setting('rabbitmq_password')
	rabbit_host = sql.get_setting('rabbitmq_host')
	rabbit_port = sql.get_setting('rabbitmq_port')
	rabbit_vhost = sql.get_setting('rabbitmq_vhost')
	if kwargs.get('rabbit_queue'):
		rabbit_queue = kwargs.get('rabbit_queue')
	else:
		rabbit_queue = sql.get_setting('rabbitmq_queue')

	credentials = pika.PlainCredentials(rabbit_user, rabbit_password)
	parameters = pika.ConnectionParameters(
		rabbit_host,
		rabbit_port,
		rabbit_vhost,
		credentials
	)

	connection = pika.BlockingConnection(parameters)
	channel = connection.channel()
	channel.queue_declare(queue=rabbit_queue)
	channel.basic_publish(exchange='', routing_key=rabbit_queue, body=message)

	connection.close()


def alert_routing(
	server_ip: str, service_id: int, group_id: int, level: str, mes: str, alert_type: str
) -> None:
	subject: str = level + ': ' + mes
	server_id: int = sql.select_server_id_by_ip(server_ip)
	checker_settings = sql.select_checker_settings_for_server(service_id, server_id)

	try:
		json_for_sending = {"user_group": group_id, "message": subject}
		send_message_to_rabbit(json.dumps(json_for_sending))
	except Exception as e:
		roxywi_common.logging('Roxy-WI server', 'error: unable to send message: ' + str(e), roxywi=1)

	for setting in checker_settings:
		if alert_type == 'service' and setting.service_alert:
			telegram_send_mess(mes, telegram_channel_id=setting.telegram_id)
			slack_send_mess(mes, slack_channel_id=setting.slack_id)

			if setting.email:
				send_email_to_server_group(subject, mes, group_id)

		if alert_type == 'backend' and setting.backend_alert:
			telegram_send_mess(mes, telegram_channel_id=setting.telegram_id)
			slack_send_mess(mes, slack_channel_id=setting.slack_id)

			if setting.email:
				send_email_to_server_group(subject, mes, group_id)

		if alert_type == 'maxconn' and setting.maxconn_alert:
			telegram_send_mess(mes, telegram_channel_id=setting.telegram_id)
			slack_send_mess(mes, slack_channel_id=setting.slack_id)

			if setting.email:
				send_email_to_server_group(subject, mes, group_id)


def send_email_to_server_group(subject: str, mes: str, group_id: int) -> None:
	try:
		users_email = sql.select_users_emails_by_group_id(group_id)

		for user_email in users_email:
			send_email(user_email.email, subject, mes)
	except Exception as e:
		roxywi_common.logging('Roxy-WI server', f'error: unable to send email: {e}', roxywi=1)


def send_email(email_to: str, subject: str, message: str) -> None:
	from smtplib import SMTP

	try:
		from email.MIMEText import MIMEText
	except Exception:
		from email.mime.text import MIMEText

	mail_ssl = sql.get_setting('mail_ssl')
	mail_from = sql.get_setting('mail_from')
	mail_smtp_host = sql.get_setting('mail_smtp_host')
	mail_smtp_port = sql.get_setting('mail_smtp_port')
	mail_smtp_user = sql.get_setting('mail_smtp_user')
	mail_smtp_password = sql.get_setting('mail_smtp_password')

	msg = MIMEText(message)
	msg['Subject'] = 'Roxy-WI: ' + subject
	msg['From'] = 'Roxy-WI <' + mail_from + '>'
	msg['To'] = email_to

	try:
		smtp_obj = SMTP(mail_smtp_host, mail_smtp_port)
		if mail_ssl:
			smtp_obj.starttls()
		smtp_obj.login(mail_smtp_user, mail_smtp_password)
		smtp_obj.send_message(msg)
		roxywi_common.logging('Roxy-WI server', f'An email has been sent to {email_to}', roxywi=1)
	except Exception as e:
		roxywi_common.logging('Roxy-WI server', f'error: unable to send email: {e}', roxywi=1)


def telegram_send_mess(mess, **kwargs):
	import telebot
	from telebot import apihelper
	token_bot = ''
	channel_name = ''

	if kwargs.get('telegram_channel_id') == 0:
		return

	if kwargs.get('telegram_channel_id'):
		telegrams = sql.get_telegram_by_id(kwargs.get('telegram_channel_id'))
	else:
		telegrams = sql.get_telegram_by_ip(kwargs.get('ip'))

	proxy = sql.get_setting('proxy')

	for telegram in telegrams:
		token_bot = telegram.token
		channel_name = telegram.chanel_name

	if token_bot == '' or channel_name == '':
		mess = " Can't send message. Add Telegram channel before use alerting at this servers group"
		roxywi_common.logging('Roxy-WI server', mess, roxywi=1)

	if proxy is not None and proxy != '' and proxy != 'None':
		apihelper.proxy = {'https': proxy}
	try:
		bot = telebot.TeleBot(token=token_bot)
		bot.send_message(chat_id=channel_name, text=mess)
	except Exception as e:
		roxywi_common.logging('Roxy-WI server', str(e), roxywi=1)


def slack_send_mess(mess, **kwargs):
	from slack_sdk import WebClient
	from slack_sdk.errors import SlackApiError
	slack_token = ''
	channel_name = ''

	if kwargs.get('slack_channel_id') == 0:
		return

	if kwargs.get('slack_channel_id'):
		slacks = sql.get_slack_by_id(kwargs.get('slack_channel_id'))
	else:
		slacks = sql.get_slack_by_ip(kwargs.get('ip'))

	proxy = sql.get_setting('proxy')

	for slack in slacks:
		slack_token = slack.token
		channel_name = slack.chanel_name

	if proxy is not None and proxy != '' and proxy != 'None':
		proxies = dict(https=proxy, http=proxy)
		client = WebClient(token=slack_token, proxies=proxies)
	else:
		client = WebClient(token=slack_token)

	try:
		client.chat_postMessage(channel='#' + channel_name, text=mess)
	except SlackApiError as e:
		roxywi_common.logging('Roxy-WI server', str(e), roxywi=1)
