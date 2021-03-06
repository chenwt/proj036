'''
CrossCorrelation.py - Calculate Cross Correlation for time series expression
============================================================================

:Author: Mike Morgan
:Release: $Id$
:Date: |today|
:Tags: Python

Purpose
-------

.. Overall purpose and function of the script>

Usage
-----

.. Example use case

Example::

   python cgat_script_template.py

Type::

   python cgat_script_template.py --help

for command line help.

Command line options
--------------------

'''

import sys
import CGAT.Experiment as E
import re
import pandas as pd
import numpy as np
import itertools
from multiprocessing.pool import ThreadPool
import CGATPipelines.Pipeline as P
import os
import pickle
import threading
import concurrent.futures


class JobGenerator(object):
    '''
    Handles data, function, mapping and job submission
    '''

    def __init__(self):
        pass

    def addMatrix(self, matrix):
        self.matrix = matrix

    def addIndices(self, index1, index2, axis=0):
        '''
        index1: iterator
          index of rows to pull out of matrix

        index2: iterator
          index of columns/pairwise rows to pull out of matrix

        axis: [0, 1]
          if axis=0 index2 are rows, if axis=1 index2 are columns
        '''

        self.index1 = index1
        self.index2 = index2
        self.axis = axis

    def pairwiseCrossCorrelate(self, indices):
        '''
        Calculate all pair-wise Cross-correlations
        for a given matrix, on row-row (axis=0),
        or row-column(axis=1)
        '''

        val1 = self.matrix.iloc[indices[0], :]
        val2 = self.matrix.iloc[indices[1], :]
        xcor = crossCorrelate(val1, val2, lag=0)[0]

        return xcor

    def mapFunction(self, function, index1, index2):
        '''
        Map a function on to a data matrix
        given the index attributes
        '''

        comb_index = itertools.product(index1, index2)
        
        xcor_array = np.array(map(self.pairwiseCrossCorrelate, comb_index))

        xcor_mat = xcor_array.reshape(len(index1),
                                      len(index2))
        return xcor_mat


def threadedMappingFunction(index1, index2, corr_object):
    '''
    Calling multpiple threads on the same object will alter the
    same underlying array.
    Generate a new array for each thread to manipulate
    '''

    # use locking to prevent multiple threads
    # altering the output array?
    corr_array = corr_object.mapFunction(corr_object.pairwiseCrossCorrelate,
                            index1, index2)
    return corr_array, index1, index2


def crossCorrelate(t, s, lag=0):
    '''
    Calculate the cross-correlation of two timeseries, s and t.
    Return the normalized correlation value at lag=n.
    Uses numpy.correlate; default is to return lag=0.
    TODO: return multiple lags?
    '''

    t_mean = np.mean(t)
    s_mean = np.mean(s)
    t_std = np.std(t)
    s_std = np.std(s)
    len_t = len(t)

    t_norm = [((x - t_mean)/(t_std * len_t)) for x in t]
    s_norm = [((y - s_mean)/s_std) for y in s]

    if lag == 0:
        xcorr = np.correlate(t_norm, s_norm)
    elif lag != 0:
        xcorr = np.correlate(t_norm, s_norm, mode=2)[len_t - 1 + lag]

    return xcorr


def chunkIt(seq, num):
    avg = len(seq)/float(num)
    out = []
    last = 0.0

    while last < len(seq):
        # if there is only one element, append it
        # to the end of the previous chunk
        if len(seq[int(last):int(last + avg)]) == 1:
            out[-1].append(seq[int(last):int(last + avg)][0])
        else:
            out.append(seq[int(last):int(last + avg)])
        last += avg

    return out
        

def main(argv=None):
    """script main.
    parses command line options in sys.argv, unless *argv* is given.
    """

    if argv is None:
        argv = sys.argv

    # setup command line parser
    parser = E.OptionParser(version="%prog version: $Id$",
                            usage=globals()["__doc__"])

    parser.add_option("-t", "--test", dest="test", type="string",
                      help="supply help")

    # add common options (-h/--help, ...) and parse command line
    (options, args) = E.Start(parser, argv=argv)

    # read in an expression matrix
    # calculate the number of pair-wise calculations
    # split into blocks of ~100K iterations
    # submit each set of iterations as a single
    # P.run() job
    infile = argv[-1]

    exprs_df = pd.read_table(infile, sep="\t", header=0,
                             index_col=0)
    n_iters = exprs_df.shape[0]
    n_jobs = (n_iters % 100) + 1
    
    job_idx = range(0, n_iters)
    idx_block = []
    
    idx_blocks = chunkIt(job_idx, n_jobs)

    E.info("Splitting computation into {} blocks".format(n_jobs**2))

    # generate the pairwise combinations of blocks
    # this gives tuples of the expression matrix
    # indices for each job
    pair_blocks = itertools.product(idx_blocks, idx_blocks)

    split_task = JobGenerator()
    split_task.addMatrix(exprs_df)
    # for each job do these things

    # need to record and retain the order of the blocks
    # in order to insert correct blocks into final matrix

    aggregated_cor = pd.DataFrame(np.zeros((n_iters, n_iters),
                                             dtype=np.float64))

    n_threads = 8
    E.info("Starting {} thread pools".format(n_threads))
    executor = concurrent.futures.ThreadPoolExecutor(n_threads)

    results = [executor.submit(threadedMappingFunction,
                               job_pair[0],
                               job_pair[1],
                               split_task) for job_pair in pair_blocks]
    
    E.info("Resolving threads")

    # what is the best timeout time to use, how fast will
    # each iteration complete?  there is a balance between the
    # overhead of the number of threads, and the total compute
    # time
    jobs_iter = 1
    wait_time = 900
    for result in concurrent.futures.as_completed(results):
        try:
            array, idx1, idx2 = result.result()
            aggregated_cor.iloc[idx1, idx2] = array
        except concurrent.futures._base.TimeoutError:
            E.info("Process still running")
            pass
        if not jobs_iter % 100:
            E.info("Processed block computations {}".format(jobs_iter))

    cor_df = pd.DataFrame(aggregated_cor)
    cor_df.index = exprs_df.index
    cor_df.columns = exprs_df.index

    cor_df.to_csv(options.stdout,
                  sep="\t", index_label=None)

    # write footer and output benchmark information.
    E.Stop()

if __name__ == "__main__":
    sys.exit(main(sys.argv))
