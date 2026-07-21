import os

# The IdP signing certificate is provisioned from the IdP's metadata at
# deploy time, not taken from the SAML response.
IDP_CERT = os.environ["SAML_IDP_CERT"]
SP_ENTITY_ID = "https://app.example.com/saml/metadata"
