# Web 2020 course project - finances journal

This is an application that helps you to share your finances with one or more groups of people (or to plan your spendings by groups for yourself)

## Launching

You will need to download Python 3 (3.7+ recommended, tested on 3.8) and a few packages, install Postgres database engine,
  create a user with password (`postgres:postgres` is default) and a database for the project (`finances` is default name).
  And then launch backend and frontend.

1. Install Python 3 and needed packages (`python -m pip install flask requests pandas psycopg2`)
2. Install Postgres (with Docker `docker run postgres` for example) and configure user and database
3. Launch backend with `python backend.py`
4. Launch frontend with `python frontend.py`

## Configuration

### Backend

For backend you can pass CLI parameters:

* -H,--db_addr - postgres host address [default localhost]
* -P,--db_port - postgres port number [default 5432]
* -d,--db_name - postgres database name [default finances]
* -U,--db_user - postgres user name [default postgres]
* -W,--db_pass - database user password [default postgres]
* -p,--port - api port number [default 3001]

### Frontend

* -p,--port - finances app frontend port [default 8080]
* -a,--api_addr - finances app API server address [default http://localhost:3001]
