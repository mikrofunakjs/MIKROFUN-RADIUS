import mysql.connector
from web.database import get_db
import datetime

def backup_database(send_to_telegram=False):
    """
    Generates a SQL dump of the database.
    If send_to_telegram is True, it will attempt to send the dump to the configured Telegram Chat.
    Returns: (sql_string, error_message)
    """
    conn = get_db()
    if not conn:
        return None, "Database connection failed"
    
    cursor = conn.cursor()
    backup_data = f"-- MikroFun Database Backup\n-- Generated: {datetime.datetime.now()}\n\n"
    backup_data += "SET FOREIGN_KEY_CHECKS=0;\n\n"
    
    try:
        # 1. Get List of Tables
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        
        for table_name_tuple in tables:
            table_name = table_name_tuple[0]
            
            # 2. Get CREATE TABLE structure
            cursor.execute(f"SHOW CREATE TABLE `{table_name}`")
            create_table_row = cursor.fetchone()
            if create_table_row:
                backup_data += f"-- Structure for table `{table_name}`\n"
                backup_data += f"DROP TABLE IF EXISTS `{table_name}`;\n"
                backup_data += f"{create_table_row[1]};\n\n"
            
            # 3. Get Table Data
            cursor.execute(f"SELECT * FROM `{table_name}`")
            rows = cursor.fetchall()
            
            if rows:
                backup_data += f"-- Data for table `{table_name}`\n"
                backup_data += f"LOCK TABLES `{table_name}` WRITE;\n"
                
                # Construct INSERT statements
                # We do this in chunks/lines to be safe
                values_list = []
                for row in rows:
                    row_values = []
                    for val in row:
                        if val is None:
                            row_values.append("NULL")
                        elif isinstance(val, (int, float)):
                            row_values.append(str(val))
                        else:
                            # Escape string values
                            # Replace \ with \\ first, then ' with \'
                            val_str = str(val).replace('\\', '\\\\').replace("'", "\\'")
                            # Handle newlines if necessary, usually safe in single quotes
                            row_values.append(f"'{val_str}'")
                    
                    values_stmt = "(" + ", ".join(row_values) + ")"
                    values_list.append(values_stmt)
                
                # Join all values
                if values_list:
                    backup_data += f"INSERT INTO `{table_name}` VALUES \n" + ",\n".join(values_list) + ";\n"
                
                backup_data += "UNLOCK TABLES;\n\n"
                
        backup_data += "SET FOREIGN_KEY_CHECKS=1;\n"
        
        if send_to_telegram:
            import os
            import tempfile
            from web.telegram_helper import send_telegram_document
            
            # Create a temporary file to send
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            filename = f"mikrofun_backup_{timestamp}.sql"
            temp_path = os.path.join(tempfile.gettempdir(), filename)
            
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.write(backup_data)
                
                caption = f"📦 *Auto-Backup Database*\nDate: `{timestamp}`"
                success, msg = send_telegram_document(temp_path, caption)
                if not success:
                    print(f"Failed to send backup to Telegram: {msg}")
            except Exception as e:
                print(f"Error preparing Telegram backup: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    
        return backup_data, None
        
    except Exception as e:
        return None, f"Backup failed: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def restore_database(sql_content):
    """
    Restores database from SQL string.
    Returns: (success_bool, message)
    """
    conn = get_db()
    if not conn:
        return False, "Database connection failed"
        
    cursor = conn.cursor()
    
    try:
        # Decode if bytes
        if isinstance(sql_content, bytes):
            sql_content = sql_content.decode('utf-8')
            
        # Prepare cursor for multi-statement
        # Execute the script
        # multi=True returns an iterator
        count = 0
        for result in cursor.execute(sql_content, multi=True):
            if result.with_rows:
                result.fetchall() # Consuming result is good practice
            count += 1
            
        conn.commit()
        return True, f"Restore successful ({count} statements executed)"
        
    except Exception as e:
        return False, f"Restore failed: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
