import psycopg2
import argparse
from flask import Flask, request, Response, jsonify, make_response
import itertools, traceback
import json, pandas
import time
from typing import Optional, List
from io import BytesIO

_version = '2021-01-15'

class Properties:
    def __init__(self, db_addr: str, db_port: int, db_name: str, db_user: str, db_pass: str, api_port: int):
        self.db_addr = db_addr
        self.db_port = db_port
        self.db_name = db_name
        self.db_user = db_user
        self.db_pass = db_pass
        self.api_port = api_port
        self._conn: Optional[psycopg2.extensions.connection] = None
    @property
    def conn_string(self) -> str:
        return f'host={self.db_addr} port={self.db_port} dbname={self.db_name}' \
                f' user={self.db_user} password={self.db_pass}'
    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.conn_string)
        return self._conn
    def close(self):
        if self._conn is not None:
            if not self._conn.closed:
                self._conn.close()
            self._conn = None

app = Flask(__name__)
props: Properties

@app.after_request
def after_request(response) -> Response:
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = '*'
    response.headers['Access-Control-Allow-Headers'] = '*'
    return response

def drop_tables() -> None:
    tables = ('messages', 'users_groups', 'operations', 'user_group_statuses', 'operation_types', 'groups', 'users')
    with props.conn.cursor() as cur:
        for table in tables:
            cur.execute(f'DROP table {table}')
        props.conn.commit()

def ensure_tables() -> None:
    with open('database_init.sql') as f:
        init: List[str] = f.read().split(';')
    with props.conn.cursor() as cur:
        for statement in init:
            if statement.strip() != '':
                cur.execute(statement)

        needed_statuses = ('creator', 'admin', 'user', 'pending', 'blocked')
        cur.execute('SELECT name FROM user_group_statuses')
        statuses = list(map(lambda x: x[0], cur.fetchall()))
        for status in needed_statuses:
            if status not in statuses:
                cur.execute('INSERT INTO user_group_statuses (name) VALUES (%s)', (status,))

        needed_operation_types = ('income', 'spending')
        cur.execute('SELECT name FROM operation_types')
        operation_types = list(map(lambda x: x[0], cur.fetchall()))
        for op_type in needed_operation_types:
            if op_type not in operation_types:
                cur.execute('INSERT INTO operation_types (name) VALUES (%s)', (op_type,))
        props.conn.commit()

# groups

@app.route('/group/<int:group_id>/', methods = ['GET'])
def get_group(group_id: int) -> Response:
    status: Optional[str] = request.args.get('status')
    with props.conn.cursor() as cur:
        cur.execute('SELECT g.name, g.creator_id, u.username, g.balance FROM groups g'
                '   JOIN users u ON u.id = g.creator_id WHERE g.id = %s', (group_id,))
        res = cur.fetchone()
        if res is None:
            return make_response(jsonify({'error': f'group with id={group_id} is not found'}), 404)
        name, creator_id, creator, balance = res
        cur.execute('SELECT u.id, u.username, ugs.name FROM users u'
                '   JOIN users_groups ug ON u.id = ug.user_id'
                '   JOIN groups g ON g.id = ug.group_id'
                '   JOIN user_group_statuses ugs on ug.status_id = ugs.id'
                '   WHERE g.id = %s' + ('' if status is None else ' AND ugs.name = %s'),
                (group_id,) if status is None else (group_id, status))
        res = pandas.DataFrame(cur.fetchall(), columns = ('id', 'username', 'status'))
        return make_response(jsonify({
            'group': {
                'id': group_id,
                'name': name,
                'creator_id': creator_id,
                'creator': creator,
                'balance': balance,
                'users': list(res.transpose().to_dict().values())
            }
        }))


@app.route('/group/', methods = ['POST'])
def add_group() -> Response:
    body = json.loads(request.data)
    if not ('name' in body and 'user' in body):
        raise Exception('Missing one of the (name, user) in request body')
    id = body['user'].isnumeric()
    with props.conn.cursor() as cur:
        cur.execute('INSERT INTO groups (name, creator_id) VALUES (%s, '
                + ('%s' if id else '(SELECT id FROM users WHERE username = %s)')
                + ') RETURNING id',
                (body['name'], body['user']))
        id = cur.fetchone()[0]
        cur.execute('INSERT INTO users_groups (user_id, group_id, status_id) VALUES'
                '   ((SELECT id FROM users where username = %s), %s, (SELECT id from user_group_statuses where name = \'creator\')) RETURNING id',
                (body['user'], id))
        props.conn.commit()
        return make_response(jsonify({'group_id': id, 'user_group_id': cur.fetchone()[0]}))

@app.route('/group/<int:id>/', methods = ['DELETE'])
def delete_group(id) -> Response:
    if not 'user' in request.args:
        return make_response(jsonify({'error': f'user parameter is missing in request path'}), 400)
    with props.conn.cursor() as cur:
        cur.execute('DELETE FROM groups WHERE id = %s', (id,))
        props.conn.commit()
        return make_response(jsonify({'result': f'deleted group with id={id}'}))

# users - groups

@app.route('/user/<user>/groups/', methods = ['GET'])
def get_user_groups(user: str) -> Response:
    id = user.isnumeric()
    status: Optional[str] = request.args.get('status')
    with props.conn.cursor() as cur:
        cur.execute('SELECT g.id, g.name, uc.count, ugs.name, g.creator_id, u.username, g.balance FROM groups g'
                '   JOIN users_groups ug ON g.id = ug.group_id'
                '   JOIN (SELECT group_id, count(*) FROM users_groups WHERE '
                '       status_id in (select id from user_group_statuses where name = \'user\' or name = \'admin\' or name = \'creator\') GROUP BY group_id)'
                '           as uc ON g.id = uc.group_id'
                '   JOIN users u ON u.id = g.creator_id'
                '   JOIN user_group_statuses ugs on ug.status_id = ugs.id' +
                ('  WHERE ug.user_id = %s' if id else ' WHERE ug.user_id = (SELECT id FROM users WHERE username = %s)') +
                ('  AND ug.status_id = ugs.name = %s' if status is not None else '') +
                '   ORDER BY g.id', (user, status) if status is not None else (user,))
        res = pandas.DataFrame(cur.fetchall(), columns = ('id', 'name', 'size', 'status', 'creator_id', 'creator', 'balance'))
        return make_response(jsonify({
            'groups': list(res.transpose().to_dict().values())
        }))

@app.route('/group/<int:group_id>/join/', methods = ['POST'])
def user_to_group(group_id: int) -> Response:
    if not 'user' in request.args:
        return make_response(jsonify({'error': f'user parameter is missing in request path'}), 400)
    id = request.args['user'].isnumeric()
    
    with props.conn.cursor() as cur:
        cur.execute('INSERT INTO users_groups (user_id, group_id, status_id) VALUES (' 
                + ('%s' if id else'(SELECT id FROM users WHERE username = %s)')
                + ', %s, (SELECT id FROM user_group_statuses WHERE name = \'pending\')) ON CONFLICT DO NOTHING',
                (request.args['user'], group_id))
        props.conn.commit()
        return make_response(jsonify({'result': 'ok'}))

@app.route('/group/<int:group_id>/status/<user>/', methods = ['PUT'])
def user_set_status(group_id: int, user: str) -> Response:
    if not 'user' in request.args:
        return make_response(jsonify({'error': f'user parameter is missing in request path'}), 400)
    if not 'status' in request.args:
        return make_response(jsonify({'error': 'new status is missing in request path'}), 400)
    user_id = user.isnumeric()
    requester_id = request.args['user'].isnumeric()
    with props.conn.cursor() as cur:
        cur.execute('SELECT id FROM user_group_statuses WHERE name = %s', (request.args['status'],))
        status_id = cur.fetchone()
        if status_id is None:
            return make_response(jsonify({'error': 'status is not found'}))
        status_id = status_id[0]
        cur.execute('SELECT s.name FROM users_groups ug JOIN user_group_statuses s on ug.status_id = s.id WHERE ug.group_id = %s AND ug.user_id = '
                + ('%s' if requester_id else '(SELECT id FROM users WHERE username = %s)'),
                (group_id, request.args['user']))
        res = cur.fetchone()
        if res is None or res[0] not in ('admin', 'creator') or request.args['status'] == 'creator' or (res[0] == 'admin' and request.args['status'] == 'admin'):
            return make_response(jsonify({'error': 'not enough rights to change someone else\'s status'}), 403)
        cur.execute('SELECT id FROM users_groups WHERE group_id = %s AND user_id = '
                + ('%s' if id else '(SELECT id FROM users WHERE username = %s)'),
                (group_id, user))
        res = cur.fetchone()
        if res is None:
            return make_response(jsonify({'error': f'user ({user}) is not found in the group ({group_id})'}), 400)
        ug_id = res[0]

        cur.execute('UPDATE users_groups SET status_id = %s WHERE id = %s', (status_id, ug_id))
        props.conn.commit()
        return make_response(jsonify({'result': 'ok'}))

# users

@app.route('/user/', methods = ['POST'])
def add_user() -> Response:
    body = json.loads(request.data)
    if not ('username' in body and 'password' in body):
        raise Exception('Missing one of the (username, password) in request body')
    if len(body['username']) < 2:
        return make_response(jsonify({'error': 'username must be at least 2 characters long'}), 400)
    if body['username'].isnumeric():
        return make_response(jsonify({'error': 'username must contain at least one letter or other symbol'}), 400)
    if sum(filter(lambda sym: sym in body['username'], list('/& '))) != 0:
        return make_response(jsonify({'error': 'username contains illegal characters'}))
    try:
        with props.conn.cursor() as cur:
            t = time.localtime()
            cur.execute('INSERT INTO users (username, password, registration_date) VALUES (%s, %s, %s) RETURNING id',
                    (body['username'], body['password'], f'{t.tm_year}-{t.tm_mon}-{t.tm_mday} {t.tm_hour}:{t.tm_min}:{t.tm_sec}'))
            props.conn.commit()
            return make_response(jsonify({'result': f'added user with id={cur.fetchone()[0]}'}))
    except psycopg2.DatabaseError as ex:
        print(ex)
        props.conn.rollback()
        return make_response(jsonify({'error': f"User with username '{body['username']} already exists"}))

@app.route('/user/<int:id>/', methods = ['GET'])
def get_user(id: int) -> Response:
    with props.conn.cursor() as cur:
        cur.execute('SELECT username FROM users WHERE id = %s', (id,))
        res = cur.fetchall()
        if len(res) == 0:
            return make_response(jsonify({'error': 'user not found'}), 404)
        return make_response(jsonify({'username': res[0]}))

@app.route('/login/', methods = ['POST'])
def login() -> Response:
    body = json.loads(request.data)
    if not ('username' in body and 'password' in body):
        return make_response(jsonify({'error': 'request body is missing username or password fields'}), 400)
    with props.conn.cursor() as cur:
        cur.execute('SELECT password FROM users WHERE username = %s', (body['username'],))
        res = cur.fetchall()
        if len(res) == 0 or res[0][0] != body['password']:
            return make_response(jsonify({'result': 'wrong username or password'}), 403)
        return make_response(jsonify({'result': 'ok'}))

# operations

@app.route('/group/<int:group_id>/operations/', methods = ['GET'])
def get_operations(group_id: int) -> Response:
    if not 'user' in request.args:
        return make_response(jsonify({'error': f'user parameter is missing in request path'}), 400)
    id = request.args['user'].isnumeric()
    page = request.args.get('page', 0)
    with props.conn.cursor() as cur:
        cur.execute('SELECT id FROM users_groups WHERE group_id = %s AND user_id = '
                + ('%s' if id else '(SELECT id FROM users WHERE username = %s)'),
                (group_id, request.args['user']))
        res = cur.fetchone()
        if res is None:
            return make_response(jsonify({'error': f'user ({request.args["user"]}) is not found in the group ({group_id})'}), 403)
        ug_id = res[0]
        cur.execute('SELECT o.id, u.username, ot.name, o.amount, o.name, o.description, o.date FROM operations o JOIN users u ON o.user_id = u.id'
                ' JOIN operation_types ot ON o.type_id = ot.id WHERE o.group_id = %s LIMIT %s OFFSET %s', (group_id, 50, page * 50))
        res = pandas.DataFrame(cur.fetchall(), columns=('id', 'user', 'type', 'amount', 'name', 'description', 'date'))
        res['date'] = res['date'].apply(lambda t: f'{t.year:02}-{t.month:02}-{t.day:02} {t.hour:02}:{t.minute:02}:{t.second:02}')
        return make_response(jsonify({
            'operations': list(res.transpose().to_dict().values())
        }))

@app.route('/group/<int:group_id>/operation/', methods = ['POST'])
def create_operation(group_id):
    body = json.loads(request.data)
    if not ('user' in body and 'type' in body and 'amount' in body and 'name' in body):
        return make_response(jsonify({'error': 'request body is missing user, type, amount or name fields'}), 400)
    if body['type'] not in ('income', 'spending'):
        return make_response(jsonify({'error': f"operation type must be one of the ('income', 'spending'), but not '{body['type']}'"}), 400)
    try:
        amount = float(body['amount'])
    except ValueError:
        return make_response(jsonify({'error': f'amount must be a floating point number (but is {body["amount"]})'}))
    id = isinstance(body['user'], int)
    with props.conn.cursor() as cur:
        cur.execute('SELECT id FROM users_groups WHERE group_id = %s AND user_id = '
                + ('%s' if id else '(SELECT id FROM users WHERE username = %s)'),
                (group_id, body['user']))
        res = cur.fetchone()
        if res is None:
            return make_response(jsonify({'error': f'user ({body["user"]}) is not found in the group ({group_id})'}), 400)
        ug_id = res[0]
        t = time.localtime()
        cur.execute('INSERT INTO operations (user_id, group_id, type_id, amount, name, description, date) VALUES ('
                + ('%s' if id else '(SELECT id FROM users WHERE username = %s)')
                + ', %s, (SELECT id FROM operation_types WHERE name = %s), %s, %s, %s, %s)',
                (body['user'], group_id, body['type'], amount, body['name'], body.get('description', ''),
                    f'{t.tm_year}-{t.tm_mon}-{t.tm_mday} {t.tm_hour}:{t.tm_min}:{t.tm_sec}'))
        cur.execute('UPDATE groups SET balance = balance ' + ('+' if body['type'] == 'income' else '-') + ' %s WHERE id = %s', (amount, group_id))
        props.conn.commit()
        return make_response(jsonify({'result': 'ok'}))

# chats

@app.route('/group/<int:group_id>/chat/', methods = ['GET'])
def get_chat(group_id: int):
    if not 'user' in request.args:
        return make_response(jsonify({'error': f'user parameter is missing in request path'}), 400)
    id = request.args['user'].isnumeric()
    page = int(request.args.get('page', 0))
    with props.conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM users_groups '
                + ('WHERE group_id = %s AND user_id = %s' if id else
                        'ug JOIN users u ON u.id = ug.user_id WHERE ug.group_id = %s AND u.username = %s'), (group_id, request.args['user'],))
        if cur.fetchone()[0] != 1:
            return make_response(jsonify({'error': f'user ({request.args["user"]}) is not in the given group ({group_id})'}), 403)
        cur.execute('SELECT m.id, ug.user_id, u.username, m.message, m.time FROM users_groups ug JOIN users u ON ug.user_id = u.id'
                '   JOIN messages m on m.user_group_id = ug.id WHERE ug.group_id = %s ORDER BY id DESC LIMIT %s OFFSET %s', (group_id, 50, 50 * page))
        res = pandas.DataFrame(cur.fetchall(), columns=('message_id', 'user_id', 'user', 'message', 'time'))
        res['time'] = res['time'].apply(lambda t: f'{t.year:02}-{t.month:02}-{t.day:02} {t.hour:02}:{t.minute:02}:{t.second:02}')
        return make_response(jsonify({
            'messages': list(res.transpose().to_dict().values())
        }))
        

@app.route('/group/<int:group_id>/chat/', methods = ['POST'])
def send_to_chat(group_id: int):
    body = json.loads(request.data)
    if not 'user' in body:
        return make_response(jsonify({'error': f'user parameter is missing in request body'}))
    id = body['user'].isnumeric()
    with props.conn.cursor() as cur:
        cur.execute('SELECT ug.id FROM users_groups ug JOIN users u ON u.id = ug.user_id WHERE u.username = %s' if id else 'WHERE ug.id = %s', (body['user'],))
        res = cur.fetchall()
        if len(res) == 0:
            return make_response(jsonify({'error': f'user ({body["user"]}) is not in the given group ({group_id})'}), 403)
        cur.execute('INSERT INTO messages (user_group_id, time, message) VALUES (%s, %s %s)', (res[0][0]))
        props.conn.commit()
        return make_response(jsonify({'result': 'ok'}))

# api help

@app.route('/', methods = ['GET'])
@app.route('/api/', methods = ['GET'])
def api():
    return make_response(jsonify({
        'version': _version,
        '_links': {
            'self': {
                'href': '/api/'
            }
        }
    }))

# errors handling

@app.errorhandler(Exception)
def any_error(error: Exception) -> Response:
    props.conn.rollback()
    print(f'path: {request.path}?{"&".join(map(lambda x: f"{x[0]}={x[1]}", request.args.items()))}, body={request.data.decode()}')
    traceback.print_exc()
    return make_response(jsonify({
        'error': str(error),
        'error_type': str(type(error)),
        'path': request.path,
        'body': request.data.decode(),
        'params': '&'.join(map(lambda x: f'{x[0]}={x[1]}', request.args.items())),
        'trace': list(itertools.chain(*map(lambda x: x.split('\n'), traceback.format_tb(error.__traceback__))))
    }), 500)

@app.errorhandler(404)
def not_found_error(_) -> Response:
    return make_response(jsonify({
        'error': 'not found',
        'path': request.path,
        'params': '&'.join(map(lambda x: f'{x[0]}={x[1]}', request.args.items())),
    }), 404)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Starts up the finances app API server')
    parser.add_argument('-H', '--db_addr', action='store', dest='db_addr',
                        help=f'postgres host address', type=str, default='localhost')
    parser.add_argument('-P', '--db_port', action='store', dest='db_port',
                        help=f'postgres port number', type=int, default=5432)
    parser.add_argument('-d', '--db_name', action='store', dest='db_name',
                        help=f'postgres database name', type=str, default='finances')
    parser.add_argument('-U', '--db_user', action='store', dest='db_user',
                        help=f'postgres user name', type=str, default='postgres')
    parser.add_argument('-W', '--db_pass', action='store', dest='db_pass',
                        help=f'database user password', type=str, default='postgres')
    parser.add_argument('-p', '--port', action='store', dest='api_port',
                        help=f'api port number', type=int, default=3001)
    args = parser.parse_args()

    props = Properties(args.db_addr, args.db_port, args.db_name, args.db_user, args.db_pass, args.api_port)

    print(f'Starting finances app API server at port {props.api_port}.')
    print(f'Using postgresql database: {props.db_user}@{props.db_addr}:{props.db_port}/{props.db_name}')

    # drop_tables()
    ensure_tables()
    app.run(host='0.0.0.0', port=props.api_port)