CREATE TABLE IF NOT EXISTS users (
    id serial PRIMARY KEY NOT NULL,
    username varchar(20) NOT NULL UNIQUE,
    password varchar(255) NOT NULL,
    registration_date timestamp NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id serial PRIMARY KEY NOT NULL,
    name varchar(100) NOT NULL,
    creator_id integer REFERENCES users(id),
    balance float NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS operation_types (
    id serial PRIMARY KEY NOT NULL,
    name varchar(30) NOT NULL
);

CREATE TABLE IF NOT EXISTS user_group_statuses (
    id serial PRIMARY KEY NOT NULL,
    name varchar(30) NOT NULL
);

CREATE TABLE IF NOT EXISTS operations (
    id serial PRIMARY KEY NOT NULL,
    user_id integer REFERENCES users(id) NOT NULL,
    group_id integer REFERENCES groups(id) ON DELETE CASCADE NOT NULL,
    type_id integer REFERENCES operation_types(id) NOT NULL,
    amount float NOT NULL,
    name varchar(50) NOT NULL,
    description varchar(255) NOT NULL DEFAULT '',
    date timestamp NOT NULL
);

CREATE TABLE IF NOT EXISTS users_groups (
    id serial PRIMARY KEY NOT NULL,
    user_id integer REFERENCES users(id) NOT NULL,
    group_id integer REFERENCES groups(id) ON DELETE CASCADE NOT NULL,
    status_id integer REFERENCES user_group_statuses NOT NULL,
    UNIQUE (user_id, group_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id serial PRIMARY KEY NOT NULL,
    user_group_id integer REFERENCES users_groups(id) ON DELETE CASCADE NOT NULL,
    time timestamp NOT NULL,
    message text NOT NULL
)