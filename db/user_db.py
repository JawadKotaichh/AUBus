import sqlite3
# aubus_db.py
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sqlite3
from typing import  Tuple
from enum import Enum



class password_hashing():

    # ---- password hashing (never store plain passwords) ----
    def __init__(self):
        self._SALT_BYTES = 16
        self._SCRYPT_N = 2**14
        self._SCRYPT_R = 8
        self._SCRYPT_P = 1
        self._DKLEN = 32

    

    def _b64(b: bytes) -> str:
        return base64.b64encode(b).decode("ascii")


    def _unb64(s: str) -> bytes:
        return base64.b64decode(s.encode("ascii"))


    def hash_password(self,plain: str) -> Tuple[str, str]:
        """
        Returns (salt_b64, hash_b64) using scrypt.
        """
        if not plain:
            raise ValueError("Password cannot be empty.")
        salt = os.urandom(self._SALT_BYTES)
        h = hashlib.scrypt(
            plain.encode("utf-8"),
            salt=salt,
            n=self._SCRYPT_N,
            r=self._SCRYPT_R,
            p=self._SCRYPT_P,
            dklen=self._DKLEN,
        )
        return self._b64(salt), self._b64(h)


    def verify_password(self,plain: str, salt_b64: str, hash_b64: str) -> bool:
        try:
            salt =self._unb64(salt_b64)
            expected =self. _unb64(hash_b64)
            h = hashlib.scrypt(
                plain.encode("utf-8"),
                salt=salt,
                n=self._SCRYPT_N,
                r=self._SCRYPT_R,
                p=self._SCRYPT_P,
                dklen=len(expected),
            )
            # constant-time compare
            return hmac.compare_digest(h, expected)
        except Exception:
            return False




def creating_initial_db():
    db=sqlite3.connect("AUBus.db")

    cursor=db.cursor()
    db.executescript('''CREATE TABLE users (
                     
                     id INT PRIMARYKEY AUTOINCREMENT,
                     name TEXT,
                     username TEXT NON NULL UNIQUE,
                     password TEXT NON NULL,
                     email TEXT NON NULL UNIQUE
                        CHECK (lower(aub_email) LIKE '%@aub.edu.lb'),
                     schedule_id INT, 
                     is_driver INT,
                     avg_rating_driver INT,
                     avg_rating_rider INT,
                     number_of_rides_driver INT,
                     number_of_riders_rider INT,
                     FOREIGN KEY (schedule_id) REFERENCES schedules(id)

                     
                     )
                     ''')
    
class User_Fields(Enum):

    username=0
    email=1
    password=2
    schedule=3


class UserExceptions(Exception):

    def __init__(self,where,reason,value=None):
        self.where=where
        self.reason=reason
        msg=self.where+": "+reason+" (got: "+value+")"
        super().__init__(msg)
    




class User ():
    

    def __init__(self,db:sqlite3.Connection,id,name,username,password,email,is_driver,schedule,avg_rating_driver:int,avg_rating_rider:int,number_of_rides_driver:int,number_of_rides_rider:int):
        self.conn=db
        self.id=id
        self.name=name
        self.username=username
        self.password='''''HOW TO HASH'''
        self.email=email
        self.is_driver=is_driver
        self.schedule=schedule
        if (bool(is_driver)):
            self.avg_rating_driver=avg_rating_driver
            self.number_of_rides_driver=number_of_rides_driver
        self.avg_rating_rider=avg_rating_rider
        self.number_of_rides_driver=number_of_rides_driver
        self.number_of_rides_rider=number_of_rides_rider

    class UserExceptions(Exception):

        def __init__(self,where,reason,value=None):
            self.where=where
            self.reason=reason
            msg=self.where+": "+reason+" (got: "+value+")"
            super().__init__(msg)
        

    def update_username(self,new_username:str):
        if  not new_username.strip():
                    
            raise UserExceptions(User_Fields.username.name,"Can't have an empty username" )
        else:
            self.username =new_username
            cur=self.conn.cursor()
            cur.execute('''
                        UPDATE users
                        SET username=?
                        WHERE id=?

                        ''', (new_username,self.id))
            self.conn.commit()
        
    def is_allowed(email: str, domain="@aub.edu.lb") -> bool:
        dom = email.rpartition("@")[2].lower().rstrip(".")
        return dom == domain.lower().rstrip(".")


    def update_email(self,new_email:str):
        if not new_email.strip():   
            raise UserExceptions(User_Fields.email.name,"Enter a Valid Email Address" )
        elif not self.is_allowed(new_email):
            ################################################################################################
            #I STILL HAVE TO HANDLE THE CASE WHERE EMAIL DOESN'T CONTAIN @##########################################
            #############################################
            raise UserExceptions(User_Fields.email.name,"Enter an AUB Email")

        else:
            self.email=new_email
            cur=self.conn.cursor()
            cur.execute('''
                        UPDATE users
                        SET email=?
                        WHERE id=?

                        ''', (new_email,self.id))
            self.conn.commit()
            


    def update_schedule(self,new_schedule_id:int):
        if not new_schedule_id:
            raise UserExceptions(User_Fields.schedule.name,"Enter a valid schedule")

        else:
            cur=self.conn.cursor()
            cur.execute('''
                            UPDATE users    
                            SET schedule_id=?
                            WHERE id=?
                            ''', (new_schedule_id,self.id))
            self.conn.commit()
        
    ######################################################################

    # COMPUTE THE NEW AVERAGE RATING AFTER IT HAS BEEN EDITED

    #####################################################################


    def adjust_avg_driver(self,latest_rating:int):

        self.avg_rating_driver=(((self.adjust_avg_driver*self.number_of_rides_driver)+latest_rating)/(self.number_of_rides_driver+1))
        self.number_of_rides_driver+=1

        cur=self.conn.cursor()
        cur.execute('''
                        UPDATE users    
                        SET average_rating_driver=?
                        SET number_of_rides_driver=?
                        WHERE id=?
                        ''', (self.avg_rating_driver,self.number_of_rides_driver,self.id))
        self.conn.commit()

    def adjust_avg_rider(self,latest_rating:int):

        self.avg_rating_rider=(((self.adjust_avg_rider*self.number_of_rides_rider)+latest_rating)/(self.number_of_rides_rider+1))
        self.number_of_rides_rider+=1

        cur=self.conn.cursor()
        cur.execute('''
                        UPDATE users    
                        SET average_rating_rider=?
                        SET number_of_rides_rider=?
                        WHERE id=?
                        ''', (self.avg_rating_rider,self.number_of_rides_rider,self.id))
        self.conn.commit()

    def get_is_driver(self):
        return self.is_driver
    
    def get_trips_driver(self):

        cur=self.conn.cursor()

        cur.execute('''

                    SELECT *,
                    FROM trips
                    WHERE driver_id=?



                    ''',(self.id))
        

        return cur.fetchall() #returns list of tuples
    
    def get_trips_rider(self):

        cur=self.conn.cursor()

        cur.execute('''

                    SELECT *,
                    FROM trips
                    WHERE rider_id=?



                    ''',(self.id))
        

        return cur.fetchall() #returns list of tuples





    
