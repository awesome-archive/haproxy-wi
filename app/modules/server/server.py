import json

import modules.db.sql as sql
import modules.common.common as common
import modules.roxywi.common as roxywi_common
from modules.server import ssh_connection
import modules.roxy_wi_tools as roxy_wi_tools

get_config_var = roxy_wi_tools.GetConfigVar()


def return_ssh_keys_path(server_ip: str, **kwargs) -> dict:
	lib_path = get_config_var.get_config_var('main', 'lib_path')
	ssh_settings = {}

	if kwargs.get('id'):
		sshs = sql.select_ssh(id=kwargs.get('id'))
	else:
		sshs = sql.select_ssh(serv=server_ip)

	for ssh in sshs:
		ssh_settings.setdefault('enabled', ssh.enable)
		ssh_settings.setdefault('user', ssh.username)
		ssh_settings.setdefault('password', ssh.password)
		ssh_key = f'{lib_path}/keys/{ssh.name}.pem' if ssh.enable == 1 else ''
		ssh_settings.setdefault('key', ssh_key)

	ssh_port = [str(server[10]) for server in sql.select_servers(server=server_ip)]
	ssh_settings.setdefault('port', ssh_port[0])

	return ssh_settings


def ssh_connect(server_ip):
	ssh_settings = return_ssh_keys_path(server_ip)
	ssh = ssh_connection.SshConnection(server_ip, ssh_settings['port'], ssh_settings['user'],
										ssh_settings['password'], ssh_settings['enabled'], ssh_settings['key'])

	return ssh


def ssh_command(server_ip: str, commands: list, **kwargs):
	if server_ip == '':
		return 'error: IP cannot be empty'
	with ssh_connect(server_ip) as ssh:
		for command in commands:
			try:
				stdin, stdout, stderr = ssh.run_command(command)
			except Exception as e:
				roxywi_common.logging('Roxy-WI server', f' Something wrong with SSH connection. Probably sudo with password {e}', roxywi=1)
				return str(e)

			try:
				if kwargs.get('raw'):
					return stdout.readlines()
				if kwargs.get("ip") == "1":
					show_ip(stdout)
				elif kwargs.get("show_log") == "1":
					import modules.roxywi.logs as roxywi_logs

					return roxywi_logs.show_log(stdout, grep=kwargs.get("grep"))
				elif kwargs.get('return_err') == 1:
					return stderr.read().decode(encoding='UTF-8')
				else:
					return stdout.read().decode(encoding='UTF-8')
			except Exception as e:
				roxywi_common.logging('Roxy-WI server', f' Something wrong with SSH connection. Probably sudo with password {e}', roxywi=1)

			for line in stderr.readlines():
				if line:
					print(f'error: {line}')
					roxywi_common.logging('Roxy-WI server', f' {line}', roxywi=1)


def subprocess_execute(cmd):
	import subprocess
	p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, universal_newlines=True)
	stdout, stderr = p.communicate()
	output = stdout.splitlines()

	return output, stderr


def is_file_exists(server_ip: str, file: str) -> bool:
	cmd = [f'[ -f {file} ] && echo yes || echo no']

	out = ssh_command(server_ip, cmd)
	return True if 'yes' in out else False


def is_service_active(server_ip: str, service_name: str) -> bool:
	cmd = [f'systemctl is-active {service_name}']

	out = ssh_command(server_ip, cmd)
	out = out.strip()
	return True if 'active' == out else False


def get_remote_files(server_ip: str, config_dir: str, file_format: str):
	config_dir = common.return_nice_path(config_dir)
	if file_format == 'conf':
		commands = [f'sudo ls {config_dir}*/*.{file_format}']
	else:
		commands = [f'sudo ls {config_dir}|grep {file_format}$']
	config_files = ssh_command(server_ip, commands)

	return config_files


def show_ip(stdout):
	for line in stdout:
		if "Permission denied" in line:
			print(f'error: {line}')
		else:
			print(line)


def get_system_info(server_ip: str) -> str:
	server_ip = common.is_ip_or_dns(server_ip)
	if server_ip == '':
		return 'error: IP cannot be empty'

	server_id = sql.select_server_id_by_ip(server_ip)

	command = ["sudo lshw -quiet -json"]
	try:
		sys_info_returned = ssh_command(server_ip, command)
	except Exception as e:
		raise e
	command = ['sudo hostnamectl |grep "Operating System"|awk -F":" \'{print $2}\'']
	try:
		os_info = ssh_command(server_ip, command)
	except Exception as e:
		raise e
	os_info = os_info.strip()
	system_info = json.loads(sys_info_returned)

	sys_info = {'hostname': system_info['id'], 'family': ''}
	cpu = {'cpu_model': '', 'cpu_core': 0, 'cpu_thread': 0, 'hz': 0}
	network = {}
	ram = {'slots': 0, 'size': 0}
	disks = {}

	try:
		sys_info['family'] = system_info['configuration']['family']
	except Exception:
		pass

	for i in system_info['children']:
		if i['class'] == 'network':
			try:
				ip = i['configuration']['ip']
			except Exception:
				ip = ''
			network[i['logicalname']] = {
				'description': i['description'],
				'mac': i['serial'],
				'ip': ip
			}
		for k, j in i.items():
			if isinstance(j, list):
				for b in j:
					try:
						if b['class'] == 'processor':
							cpu['cpu_model'] = b['product']
							cpu['cpu_core'] += 1
							cpu['hz'] = round(int(b['capacity']) / 1000000)
							try:
								cpu['cpu_thread'] += int(b['configuration']['threads'])
							except Exception:
								cpu['cpu_thread'] = 1
					except Exception:
						pass

					try:
						if b['id'] == 'memory':
							ram['size'] = round(b['size'] / 1073741824)
							for memory in b['children']:
								ram['slots'] += 1
					except Exception:
						pass

					try:
						if b['class'] == 'storage':
							for p, pval in b.items():
								if isinstance(pval, list):
									for disks_info in pval:
										for volume_info in disks_info['children']:
											if isinstance(volume_info['logicalname'], list):
												volume_name = volume_info['logicalname'][0]
												mount_point = volume_info['logicalname'][1]
												size = round(volume_info['capacity'] / 1073741824)
												size = str(size) + 'Gb'
												fs = volume_info['configuration']['mount.fstype']
												state = volume_info['configuration']['state']
												disks[volume_name] = {
													'mount_point': mount_point,
													'size': size,
													'fs': fs,
													'state': state
												}
					except Exception:
						pass

					try:
						if b['class'] == 'bridge':
							if 'children' in b:
								for s in b['children']:
									if s['class'] == 'network':
										if 'children' in s:
											for net in s['children']:
												network[net['logicalname']] = {
													'description': net['description'],
													'mac': net['serial']
												}
									if s['class'] == 'storage':
										for p, pval in s.items():
											if isinstance(pval, list):
												for disks_info in pval:
													if 'children' in disks_info:
														for volume_info in disks_info['children']:
															if isinstance(volume_info['logicalname'], dict):
																volume_name = volume_info['logicalname'][0]
																mount_point = volume_info['logicalname'][1]
																size = round(volume_info['size'] / 1073741824)
																size = str(size) + 'Gb'
																fs = volume_info['configuration']['mount.fstype']
																state = volume_info['configuration']['state']
																disks[volume_name] = {
																	'mount_point': mount_point,
																	'size': size,
																	'fs': fs,
																	'state': state
																}
									for z, n in s.items():
										if isinstance(n, list):
											for y in n:
												if y['class'] == 'network':
													try:
														for q in y['children']:
															try:
																ip = q['configuration']['ip']
															except Exception:
																ip = ''
															network[q['logicalname']] = {
																'description': q['description'],
																'mac': q['serial'],
																'ip': ip}
													except Exception:
														try:
															network[y['logicalname']] = {
																'description': y['description'],
																'mac': y['serial'],
																'ip': y['configuration']['ip']}
														except Exception:
															pass
												if y['class'] == 'disk':
													try:
														for q in y['children']:
															try:
																if isinstance(q['logicalname'], list):
																	volume_name = q['logicalname'][0]
																	mount_point = q['logicalname'][1]
																	size = round(q['capacity'] / 1073741824)
																	size = str(size) + 'Gb'
																	fs = q['configuration']['mount.fstype']
																	state = q['configuration']['state']
																	disks[volume_name] = {
																		'mount_point': mount_point,
																		'size': size,
																		'fs': fs,
																		'state': state
																	}
															except Exception as e:
																print(e)
													except Exception:
														pass
												if y['class'] == 'storage' or y['class'] == 'generic':
													try:
														for q in y['children']:
															for o in q['children']:
																try:
																	volume_name = o['logicalname']
																	mount_point = ''
																	size = round(o['size'] / 1073741824)
																	size = str(size) + 'Gb'
																	fs = ''
																	state = ''
																	disks[volume_name] = {
																		'mount_point': mount_point,
																		'size': size,
																		'fs': fs,
																		'state': state
																	}
																except Exception:
																	pass
																for w in o['children']:
																	try:
																		if isinstance(w['logicalname'], list):
																			volume_name = w['logicalname'][0]
																			mount_point = w['logicalname'][1]
																			try:
																				size = round(w['size'] / 1073741824)
																				size = str(size) + 'Gb'
																			except Exception:
																				size = ''
																			fs = w['configuration']['mount.fstype']
																			state = w['configuration']['state']
																			disks[volume_name] = {
																				'mount_point': mount_point,
																				'size': size,
																				'fs': fs,
																				'state': state
																			}
																	except Exception:
																		pass
													except Exception:
														pass
													try:
														for q, qval in y.items():
															if isinstance(qval, list):
																for o in qval:
																	for w in o['children']:
																		if isinstance(w['logicalname'], list):
																			volume_name = w['logicalname'][0]
																			mount_point = w['logicalname'][1]
																			size = round(w['size'] / 1073741824)
																			size = str(size) + 'Gb'
																			fs = w['configuration']['mount.fstype']
																			state = w['configuration']['state']
																			disks[volume_name] = {
																				'mount_point': mount_point,
																				'size': size,
																				'fs': fs,
																				'state': state
																			}
													except Exception:
														pass
					except Exception:
						pass

	try:
		sql.insert_system_info(server_id, os_info, sys_info, cpu, ram, network, disks)
	except Exception as e:
		raise e
