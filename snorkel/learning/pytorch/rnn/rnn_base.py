from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import numpy as np
import torch
import torch.nn as nn
from builtins import *

import warnings

from snorkel.learning.pytorch.noise_aware_model import TorchNoiseAwareModel
from snorkel.models import Candidate
from .utils import candidate_to_tokens, SymbolTable

SD = 0.1

def mark(l, h, idx):
    """Produce markers based on argument positions
    
    :param l: sentence position of first word in argument
    :param h: sentence position of last word in argument
    :param idx: argument index (1 or 2)
    """
    return [(l, "{}{}".format('~~[[', idx)), (h+1, "{}{}".format(idx, ']]~~'))]


def mark_sentence(s, args):
    """Insert markers around relation arguments in word sequence
    
    :param s: list of tokens in sentence
    :param args: list of triples (l, h, idx) as per @_mark(...) corresponding
               to relation arguments
    
    Example: Then Barack married Michelle.  
         ->  Then ~~[[1 Barack 1]]~~ married ~~[[2 Michelle 2]]~~.
    """
    marks = sorted([y for m in args for y in mark(*m)], reverse=True)
    x = list(s)
    for k, v in marks:
        x.insert(k, v)
    return x

class RNNBase(TorchNoiseAwareModel):
    representation=True
    
    def marginals(self, X, batch_size=None):
        """
        Compute the marginals for the given candidates X.
        Split into batches to avoid OOM errors, then call _marginals_batch;
        defaults to no batching.
        """
        if not batch_size:
            batch_size = len(X)
    
        if isinstance(X[0], Candidate):
            X_test = self._preprocess_data(X)
        else:
            X_test = X
    
        marginals = torch.Tensor([])
        n = len(X_test)
        
        for batch in range(0, n, batch_size):
            
            if batch_size < len(X_test[batch:batch+batch_size]):
                batch_size = batch_size
            else:
                batch_size = len(X_test[batch:batch+batch_size])
            
            hidden_state = self.initalize_hidden_state(batch_size)
            
            max_batch_length = max(map(len, X_test[batch:batch+batch_size]))
            packed_X_test = torch.autograd.Variable(torch.zeros(batch_size, max_batch_length)).long()
            
            for idx, seq in enumerate(X_test[batch:batch+batch_size]):
                packed_X_test[idx, :len(seq)] = torch.LongTensor(seq)
            
            output = self.forward(packed_X_test, hidden_state)
            marginals = torch.cat((marginals, output), 0)

        if self.cardinality == 2: 
            marginals = nn.functional.sigmoid(marginals)
            marginals = np.array(marginals[:,0].data)
        else:
            marginals = nn.functional.softmax(torch.stack(marginals))

        return marginals

    
    def _preprocess_data(self, candidates, extend=False):
        """Convert candidate sentences to lookup sequences
        
        :param candidates: candidates to process
        :param extend: extend symbol table for tokens (train), or lookup (test)?
        """
        if not hasattr(self, 'word_dict'):
            self.word_dict = SymbolTable()
        data = []
        for candidate in candidates:
            # Mark sentence
            args = [
                (candidate[0].get_word_start(), candidate[0].get_word_end(), 1),
                (candidate[1].get_word_start(), candidate[1].get_word_end(), 2)
            ]
            s = mark_sentence(candidate_to_tokens(candidate), args)
            # Either extend word table or retrieve from it
            f = self.word_dict.get if extend else self.word_dict.lookup
            data.append(np.array(list(map(f, s))))
            
        return data


    def train(self, X_train, Y_train, X_dev=None, embedding_dim=100, **kwargs):
        """
        Perform preprocessing of data, construct dataset-specific model, then
        train.
        """
        # Text preprocessing
        X_train = self._preprocess_data(X_train, extend=True)
        if X_dev is not None:
            X_dev = self._preprocess_data(X_dev, extend=False)
        self.embedding_dim = embedding_dim
        self.embedding = nn.Embedding(self.word_dict.len(), self.embedding_dim)

        # Train model- note we pass word_dict through here so it gets saved...
        super(RNNBase, self).train(X_train, Y_train, X_dev=X_dev,
            word_dict=self.word_dict, **kwargs)

