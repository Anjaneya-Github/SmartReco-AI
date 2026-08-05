"""
app/auth
---------
Authentication and authorisation utilities.

Public surface
~~~~~~~~~~~~~~
from app.auth.password     import hash_password, verify_password
from app.auth.jwt          import create_access_token, decode_access_token
from app.auth.dependencies import get_current_user, get_current_admin
"""
