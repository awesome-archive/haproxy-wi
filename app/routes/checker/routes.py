from flask import render_template, request, g
from flask_login import login_required

from app.routes.checker import bp
from middleware import get_user_params
import app.modules.db.sql as sql
import app.modules.common.common as common
import app.modules.roxywi.common as roxywi_common
import app.modules.tools.alerting as alerting
import app.modules.tools.checker as checker_mod


@bp.before_request
@login_required
def before_request():
    """ Protect all of the admin endpoints. """
    pass


@bp.route('/settings')
@get_user_params()
def checker_settings():
    roxywi_common.check_user_group_for_flask()

    return render_template('checker.html')


@bp.post('/settings/update')
def update_settings():
    service = request.form.get('service')
    setting_id = int(request.form.get('setting_id'))
    email = int(request.form.get('email'))
    service_alert = int(request.form.get('server'))
    telegram_id = int(request.form.get('telegram_id'))
    slack_id = int(request.form.get('slack_id'))
    pd_id = int(request.form.get('pd_id'))

    if service == 'haproxy':
        maxconn_alert = int(request.form.get('maxconn'))
        backend_alert = int(request.form.get('backend'))
        return checker_mod.update_haproxy_settings(
            setting_id, email, service_alert, backend_alert, maxconn_alert, telegram_id, slack_id, pd_id
        )
    elif service in ('nginx', 'apache'):
        return checker_mod.update_service_settings(setting_id, email, service_alert, telegram_id, slack_id, pd_id)
    else:
        backend_alert = int(request.form.get('backend'))
        return checker_mod.update_keepalived_settings(setting_id, email, service_alert, backend_alert, telegram_id, slack_id, pd_id)


@bp.route('/settings/load')
def load_checker():
    return checker_mod.load_checker()


@bp.route('/history')
@get_user_params()
def checker_history():
    roxywi_common.check_user_group_for_flask()

    kwargs = {
        'lang': g.user_params['lang'],
        'smon': sql.alerts_history('Checker', g.user_params['group_id']),
        'user_subscription': roxywi_common.return_user_subscription(),
    }

    return render_template('smon/checker_history.html', **kwargs)


@bp.route('/check/<channel_id>/<receiver_name>')
def check_receiver(channel_id, receiver_name):
    channel_id = common.checkAjaxInput(channel_id)
    receiver_name = common.checkAjaxInput(receiver_name)

    return alerting.check_receiver(channel_id, receiver_name)


@bp.route('/check/rabbit')
def check_rabbit():
    return alerting.check_rabbit_alert()


@bp.route('/check/email')
def check_email():
    return alerting.check_email_alert()


@bp.route('/receiver/<receiver_name>', methods=['PUT', 'POST', 'DELETE'])
def receiver(receiver_name):
    if request.method == 'POST':
        token = common.checkAjaxInput(request.form.get('receiver'))
        channel = common.checkAjaxInput(request.form.get('channel'))
        group = common.checkAjaxInput(request.form.get('group'))
        page = common.checkAjaxInput(request.form.get('page'))
        page = page.split("#")[0]

        return alerting.add_receiver_channel(receiver_name, token, channel, group, page)
    elif request.method == 'PUT':
        token = common.checkAjaxInput(request.form.get('receiver_token'))
        channel = common.checkAjaxInput(request.form.get('channel'))
        group = common.checkAjaxInput(request.form.get('group'))
        user_id = common.checkAjaxInput(request.form.get('id'))

        return alerting.update_receiver_channel(receiver_name, token, channel, group, user_id)
    elif request.method == 'DELETE':
        channel_id = common.checkAjaxInput(request.form.get('channel_id'))

        return alerting.delete_receiver_channel(channel_id, receiver_name)
