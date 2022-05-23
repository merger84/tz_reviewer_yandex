from airflow import DAG
from airflow.utils.dates import days_ago
from airflow.operators.python_operator import PythonOperator
from airflow.operators.postgres_operator import PostgresOperator

from datetime import datetime
import requests
import psycopg2


day_load = '{{ ds }}'   # '2020-01-01'


default_args = {
    'owner': 'airflow',
    'start_date': days_ago(2),
    'provide_context': True
}


def extract(**kwargs):
    ''' Загрузим API с exchangerate.host на текущий момент для BTC/USD (Биткоин к доллару) '''
    url = 'https://api.exchangerate.host/convert?from=USD&to=BTC'
    params = dict(date=day_load)
    response = requests.get(url, params=params)
    data = response.json()
    print(data)
    kwargs['ti'].xcom_push(key='order_data', value=data)


def transform(**kwargs):
    ''' из полученных данных выберем нужные значения по валютной паре BTC/USD (Биткоин к доллару) '''
    ti = kwargs['ti']
    order_data = ti.xcom_pull(task_ids='extract_data', key='order_data')
    print(f'order_data = {order_data}')
    result_convert = order_data['result']
    print(f'result_convert = {result_convert}')
    try:
        value_convert = '{:f}'.format(result_convert)
        print(f'Реузльтат {value_convert}')
    except:
        value_convert = 'NULL'
        print('Реузльтат Null')
    ti.xcom_push('value_convert', value_convert)


# соединение с базой данных и создадим нужную нам таблицу, если ее нету
def create_table(**kwargs):
    try:
        conn = psycopg2.connect(user = 'airflow',
                            password = 'airflow',
                                host = 'postgres',    
                                port = '5432',    
                            database = 'postgres')
        try:
            with conn:
                with conn.cursor() as curs:
                    # Создадим Таблицу price_desc для сохранения данных с exchangerate.host
                    # price_id - порядковый номер, сurrency_pair - валютная пара, price_date - дата, price - текущий курс
                    SQL = \
                        """CREATE TABLE IF NOT EXISTS price_desc (
                            price_id SERIAL PRIMARY KEY,
                            сurrency_pair VARCHAR NOT NULL,
                            price_date DATE NOT NULL,
                            price NUMERIC
                        );"""
                    curs.execute(SQL)
        finally:
            conn.close()
    except Exception as e:        
        print(f'ERROR in CREATE TABLE: {e}')


# удалим все записи за указанный день
def generate_query_delete(**kwargs):
    with open("/tmp/postgres_query.sql", "w") as f:
        f.write(
            "DELETE FROM public.price_desc "
            f"WHERE price_date = '{day_load}'::date;"
        )


with DAG(
    dag_id="api_exchangerate",        
    schedule_interval= "0 0/3 * * *",
    template_searchpath="/tmp",
    default_args=default_args,
    max_active_runs=1,
    catchup=False
) as dag:

    extract_task = PythonOperator(
        task_id="extract_data",
        python_callable=extract
    )

    transform_task = PythonOperator(
        task_id="transform_data",
        python_callable=transform
    )

    create_task = PythonOperator(
        task_id="create_table",
        python_callable=create_table
    )

    gen_query_del = PythonOperator(
        task_id="gen_query_del",
        python_callable=generate_query_delete
    )

    del_date_load = PostgresOperator(
        task_id="del_date_load",
        postgres_conn_id="postgres",
        sql="postgres_query.sql"
    )

    load_task = PostgresOperator(
        task_id="load",
        postgres_conn_id="postgres",
        sql=f"insert into public.price_desc (сurrency_pair, price_date, price)\
                values('BTC/USD', '{day_load}'::date, " + 
            "{{ ti.xcom_pull(task_ids='transform_data', key='value_convert') }});"
    )


    extract_task >> [transform_task, create_task, gen_query_del] >> del_date_load >> load_task