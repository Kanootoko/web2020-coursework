from flask import Flask, request, redirect, Response, make_response, render_template, session
import argparse
import requests
from typing import Optional
import os
import traceback, itertools

_version = '2021-01-15'

class Properties:
    def __init__(self, api_addr):
        self.api_addr = api_addr
    
app = Flask(__name__)
properties: Properties

must_login_error = '/?error=You must log in to see this page'

@app.route('/', methods = ['GET'])
def main_page() -> Response:
    if 'user' in session:
        result = requests.get(properties.api_addr + f'/user/{session["user"]}/groups/')
        j = result.json()
        return make_response(render_template('index_user.html', user=session['user'], groups=(j['groups'] if 'groups' in j else list()), error_message=request.args.get('error')))
    else:
        return make_response(render_template('index_anonymous.html', error_message=request.args.get('error')))

@app.route('/login/', methods = ['GET'])
def login_page() -> Response:
    if 'login' in session:
        return make_response(redirect('/'))
    return make_response(render_template('login.html', error_message=request.args.get('error')))

@app.route('/registration/', methods = ['GET'])
def registration_page() -> Response:
    if 'login' in session:
        return make_response(redirect('/'))
    return make_response(render_template('registration.html', error_message=request.args.get('error')))

@app.route('/login/', methods = ['POST'])
def login() -> Response:
    if 'username' not in request.form or 'password' not in request.form:
        return make_response(redirect('/login?error="username" or "pasword" is missing'))
    username = request.form.get('username')
    password = request.form.get('password')
    result = requests.post(properties.api_addr + '/login/', json={'username': username, 'password': password})
    if result.status_code == 200 and result.json()['result'] == 'ok':
        session['user'] = username
        return make_response(redirect('/'))
    else:
        return make_response(redirect('/login?error=wrong login or password'))

@app.route('/registration/', methods = ['POST'])
def registration() -> Response:
    if 'username' not in request.form or 'password1' not in request.form or 'password2' not in request.form:
        return make_response(redirect('/registration?error="username", "password1" or "password2" is missing'))
    username = request.form.get('username')
    password1 = request.form.get('password1')
    password2 = request.form.get('password2')
    if password1 != password2:
        return make_response(redirect('/registration?error=passwords do not match'))
    result = requests.post(properties.api_addr + '/user/', json={'username': username, 'password': password1})
    j = result.json()
    if result.status_code == 200 and 'result' in j:
        return make_response(redirect('/'))
    else:
        return make_response(redirect(f'/registration?error={j["error"] if "error" in j else "unknown error"}'))

@app.route('/logout/', methods = ['POST'])
def logout() -> Response:
    del session['user']
    return make_response(redirect('/'))

@app.route('/group/<int:group_id>/', methods = ['GET'])
def group_page(group_id: int) -> Response:
    if not 'user' in session:
        return make_response(redirect(must_login_error))
    result_group = requests.get(properties.api_addr + f'/group/{group_id}/?user={session["user"]}')
    result_operations = requests.get(properties.api_addr + f'/group/{group_id}/operations/?user={session["user"]}')
    result_chat = requests.get(properties.api_addr + f'/group/{group_id}/chat/?user={session["user"]}')
    if result_group.status_code != 200 or result_operations.status_code != 200 or result_chat.status_code != 200:
        return make_response(redirect('/'))
    j_group, j_operations, j_chat = result_group.json()['group'], result_operations.json(), result_chat.json()
    users_statuses = dict(map(lambda x: (x['username'], x['status']), j_group['users']))
    return make_response(render_template('group.html', id = group_id, name = j_group['name'], user = session['user'],
            role = users_statuses[session['user']], balance = j_group['balance'],
            operations = j_operations['operations'], chat = j_chat['messages']))

@app.route('/group/new/', methods = ['GET'])
def create_group_page() -> Response:
    if not 'user' in session:
        return make_response(redirect(must_login_error))
    return make_response(render_template('group_create.html'))

@app.route('/group/new/', methods = ['POST'])
def create_group() -> Response:
    if not 'user' in session:
        return make_response(redirect(must_login_error))
    if not 'name' in request.form or request.form['name'] == '':
        return make_response(redirect('/group/new/?errror=You must fill group name'))
    requests.post(properties.api_addr + '/group/', json={
        'user': session['user'],
        'name': request.form['name']
    })
    return make_response(redirect('/'))

@app.route('/group/join/', methods = ['GET'])
def join_group_page() -> Response:
    if not 'user' in session:
        return make_response(redirect(must_login_error))
    return make_response(render_template('group_join.html'))

@app.route('/group/join/', methods = ['POST'])
def join_group() -> Response:
    if not 'user' in session:
        return make_response(redirect(must_login_error))
    if not 'id' in request.form:
        return make_response(redirect('/'))
    group_id = request.form['id']
    res = requests.post(properties.api_addr + f'/group/{group_id}/join/?user={session["user"]}').json()
    if not 'result' in res:
        return make_response(redirect('/group/join/?error=Something went wrong, try again'))
    if res['result'] != 'ok':
        return make_response(redirect(f'/group/join/?error=Error: {res["result"]}'))
    return make_response(redirect('/'))

@app.route('/group/<int:group_id>/manage/', methods = ['GET'])
def group_manage_page(group_id: int) -> Response:
    if not 'user' in session:
        return make_response(redirect(must_login_error))
    group = requests.get(properties.api_addr + f'/group/{group_id}/').json()['group']
    users_statuses_name = dict(map(lambda x: (x['username'], x['status']), group['users']))
    if users_statuses_name[session['user']] not in ('admin', 'creator'):
        return make_response(redirect(f'/group/{group_id}/'))
    return make_response(render_template('group_manage.html', id = group['id'], name = group['name'], users = group['users']))

@app.route('/group/<int:group_id>/status/<int:user_id>/', methods = ['POST'])
def change_user_status(group_id: int, user_id: int) -> Response:
    if not 'user' in session:
        return make_response(redirect(must_login_error))
    res = requests.get(properties.api_addr + f'/group/{group_id}/').json()['group']
    users_statuses_name = dict(map(lambda x: (x['username'], x['status']), res['users']))
    users_statuses_id = dict(map(lambda x: (x['id'], x['status']), res['users']))
    if users_statuses_name[session['user']] in ('admin', 'creator') and 'status' in request.args:
        oldrole = users_statuses_id[user_id]
        newrole = request.args['status']
        role = users_statuses_name[session['user']]
        if role in ('admin', 'creator') and oldrole != 'creator' and \
                oldrole in ('pending', 'blocked', 'user') and newrole in ('blocked', 'user') or \
                (oldrole == 'admin' or newrole == 'admin') and role == 'creator':
            requests.put(properties.api_addr + f'/group/{group_id}/status/{user_id}?status={newrole}&user={session["user"]}')
    return make_response(redirect(f'/group/{group_id}/manage'))

@app.route('/group/<int:group_id>/operation/', methods = ['POST'])
def create_operation(group_id: int) -> Response:
    if not 'user' in session:
        return make_response(redirect(must_login_error))
    if not ('amount' in request.form and 'type' in request.form and 'name' in request.form and 'description' in request.form):
        return make_response(redirect(f'/group/{group_id}/'))
    requests.post(properties.api_addr + f'/group/{group_id}/operation/', json={'user': session['user'],
            'amount': request.form['amount'], 'type': request.form['type'], 'name': request.form['name'], 'description': request.form['description']})
    return make_response(redirect(f'/group/{group_id}/'))

# errors handling

@app.errorhandler(Exception)
def any_error(error: Exception) -> Response:
    debug = True
    print(f'path: {request.path}?{"&".join(map(lambda x: f"{x[0]}={x[1]}", request.args.items()))}, body={request.data.decode()}')
    traceback.print_exc()
    if debug:
        return make_response(render_template('error500_debug.html', error = str(error), error_type = str(type(error)),
                path = request.path, body = request.data.decode().replace('\n', '<br>'),
                params = '&'.join(map(lambda x: f'{x[0]}={x[1]}', request.args.items())),
                trace = list(itertools.chain(*map(lambda x: x.split('\n'), traceback.format_tb(error.__traceback__))))
        ), 500)
    else:
        return make_response(render_template('error500.html'))

@app.errorhandler(404)
def not_found_error(_) -> Response:
    return make_response(render_template('error404.html'))

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Starts up the finances app frontend server')
    parser.add_argument('-p', '--port', action='store', dest='port',
                        help=f'finances app frontend port', type=int, default=8080)
    parser.add_argument('-a', '--api_addr', action='store', dest='api_addr',
                        help=f'finances app API server address', type=str, default='http://localhost:3001')
    args = parser.parse_args()

    properties = Properties(args.api_addr)

    print(f'Starting finances frontend (version {_version}) server at port {args.port}')
    try:
        api_version = requests.get(properties.api_addr + '/api/').json()['version']
        print(f'Api version {api_version} is available at {properties.api_addr}')
    except Exception as ex:
        print(f'Could not get version of api: error {ex}')

    app.secret_key = os.urandom(24)
    app.run(host='0.0.0.0', port=args.port)