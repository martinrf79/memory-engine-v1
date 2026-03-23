from google.cloud import firestore

client = firestore.Client()
collection = client.collection("memories")
