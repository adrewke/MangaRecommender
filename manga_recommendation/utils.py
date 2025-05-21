from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import MultiLabelBinarizer

class GenreBinarizer(BaseEstimator, TransformerMixin):
    def __init__(self):
        self.binarizer = MultiLabelBinarizer()

    def fit(self, X, y=None):
        return self.binarizer.fit(X)

    def transform(self, X):
        return self.binarizer.transform(X)
