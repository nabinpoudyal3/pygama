import time
import numpy as np
from pprint import pprint
import matplotlib.pyplot as plt
import scipy.signal as signal


def avg_bl(waves,
           calcs,
           i_start=0,
           i_end=500,
           wfin="waveform",
           calc="bl_avg",
           test=False):
    """
    simple mean, vectorized baseline calculator
    """
    wf_block = waves["waveform"]

    # find wf means
    avgs = np.mean(wf_block[:, i_start:i_end], axis=1)

    # add the result as a new column
    calcs[calc] = avgs


def fit_bl(waves,
           calcs,
           i_start=0,
           i_end=500,
           order=1,
           wfin="waveform",
           cnames=["bl_int", "bl_slope", "bl_rms"],
           test=False):
    """
    polynomial fit [order], vectorized baseline calculator
    TODO:
    - if we made this calculator a little more general, it could do arb. orders
      on arbitary windows, so it could also be re-used to fit the wf tails.
    - also discussed on a Feb 2019 legend S/A call that using a 2nd order term
      in the baseline might be useful in high event-rate situations where the
      baseline hasn't yet fully recovered to flat.
    """
    wf_block = waves[wfin]

    # run polyfit
    wfs = wf_block[:, i_start:i_end].T
    x = np.arange(i_start, i_end)
    # note: these coeffs are reversed from normal polyfit.  should change this
    pol = np.polynomial.polynomial.polyfit(x, wfs, order).T

    # get the rms noise
    wfstd = np.std(wfs.T, axis=1)

    if test:
        iwf = 5

        ts, wf = np.arange(len(wf_block[iwf])), wf_block[iwf]
        plt.plot(ts, wf, c='b')

        blwf, blts = wfs.T[iwf], np.arange(len(wfs.T[iwf]))
        plt.plot(blts, blwf, c='r')

        b, m = pol[iwf]
        fit = lambda t: m * t + b
        plt.plot(
            blts,
            fit(blts),
            c='k',
            lw=3,
            label='baseline, pol1: \n{:.2e}*ts + {:.1f}'.format(m, b))

        plt.xlim(0, 1100)
        plt.xlabel("clock ticks", ha='right', x=1)
        plt.ylabel("ADC", ha='right', y=1)
        plt.legend(loc=2)
        plt.tight_layout()
        plt.show()
        exit()

    # add the results as new columns
    for i, c in enumerate(["bl_int", "bl_slope"]):
        calcs[c] = pol[:, i]

    calcs["bl_rms"] = wfstd


def get_max(waves, calcs, wfin="wf_trap", calc="trap_max", test=False):
    """
    calculate maxima of each row of a waveform block (e.g. a trap filter).
    note that this is very general and works w/ any wf type.
    creates two columns:  max value, and index of maximum.
    """
    wfs = waves[wfin]
    clk = waves["settings"]["clk"]  # Hz

    maxes = np.amax(wfs, axis=1)
    imaxes = np.argmax(wfs, axis=1)

    cname = wfin.split("_")[-1]
    calcs["{}_max".format(cname)] = maxes
    calcs["{}_imax".format(cname)] = imaxes

    if test:
        iwf = 5

        # for reference, show the raw wf, but scale s/t it matches the given wf
        wf = wfs[iwf]
        raw_wf = waves["wf_blsub"][iwf]
        raw_wf *= np.amax(wf) / np.amax(raw_wf)
        ts = np.arange(len(wf))

        plt.plot(ts, raw_wf, '-b', alpha=0.7, label="raw_wf, normd")
        plt.plot(ts, wf, "-k", label=wfin)
        plt.plot(ts[imaxes[iwf]], maxes[iwf], ".m", ms=20, label="max")
        plt.xlabel("clock ticks", ha='right', x=1)
        plt.ylabel("arb", ha='right', y=1)
        plt.legend()
        plt.tight_layout()
        plt.show()
        exit()


def timepoint(waves, calcs, pct, wfin="wf_savgol", calc="tp", test=False):
    """
    for an estimate of where the wf tail starts, just use pct = 100 + (delta).
    """
    wfs = waves[wfin]
    smax = calcs["savgol_max"].values

    for p in pct:
        tp_idx = np.argmax(wfs >= smax[:, None] * (p / 100.), axis=1)
        calcs["tp{}".format(p)] = tp_idx

    if test:

        wfraw = waves["wf_blsub"]

        iwf = -1
        while True:
            if iwf != -1:
                inp = input()
                if inp == "q": exit()
                if inp == "p": iwf -= 2
            iwf += 1
            print(iwf)

            wf = wfs[iwf]
            ts = np.arange(len(wf))

            plt.cla()
            plt.plot(ts, wfraw[iwf], "-b", alpha=0.6, label='raw wf')
            plt.plot(ts, wf, "-k", label=wfin)

            cmap = plt.cm.get_cmap('jet', len(pct) + 1)
            for i, tp in enumerate(pct):

                idx = calcs["tp{}".format(tp)][iwf]
                print("tp{}: idx {}  val {:.2f}".format(tp, idx, wf[idx]))

                plt.plot( idx, wf[idx], ".", c=cmap(i), ms=20,
                         label="tp{}".format(tp))

            plt.xlabel("clock ticks", ha='right', x=1)
            plt.ylabel("ADC", ha='right', y=1)
            plt.legend()
            plt.tight_layout()
            plt.show(block=False)
            plt.pause(0.01)


def ftp(waves, calcs, wf1="wf_etrap", wf2="wf_atrap", test=False):
    """
    Jason says the fixed time pickoff for MJD ends up being 2 us into the
    2.5 us trap, and the choice is not super important.

    Ian says the trap flat top needs to be as long as a typical rising edge,
    should verify that 2.5 us is good enough for MJ60

    It looks like the asym trap (0.04-0.1-2) is much better at finding
    the t0 time than the short trap (1-1.5-1).  And, by padding it half the
    asym trap's width (in `transforms.trap`), the t0 we find is actually a
    pretty good t0 estimate for the raw waveform as well.
    """
    wflong = waves[wf1]
    wfshort = waves[wf2]

    # get trap settings from metadata
    trap1, trap2 = None, None
    for tr in waves["settings"]["trap"]:
        if tr["wfout"] == wf1: trap1 = tr
        if tr["wfout"] == wf2: trap2 = tr

    # define the fixed time pickoff based on the energy trap settings
    nsamp = 1e10 / waves["settings"]["clk"]
    ftp = int(nsamp * (trap1["rise"] + trap1["flat"]))

    # "walk back" from the short trap's max to get t0.
    # this is less dependent on the trap's baseline noise.
    # MJD uses a threshold of 2 ADC, hardcoded.
    thresh = 2
    short = wf2.split("_")[1]
    t0 = np.zeros(wfshort.shape[0], dtype=int)
    for i, wf in enumerate(wfshort):
        # damn, i guess i have to loop over the rows
        imax = calcs[short + "_imax"][i]
        trunc = wfshort[i][:imax][::-1]
        t0[i] = len(trunc) - np.where(trunc < thresh)[0][0]

    # save the t0 idx
    calcs['t0'] = t0

    # save the t_ftp idx
    t_ftp = t0 + ftp
    t_ftp[t_ftp >= wflong.shape[1]] = 0  # if t_ftp > len(wf), it failed
    calcs['t_ftp'] = t_ftp

    # save the e_ftp energy
    row_idx = np.arange(wflong.shape[0])
    e_ftp = wflong[np.arange(wflong.shape[0]), t_ftp]
    calcs['e_ftp'] = e_ftp

    if test:

        wfs = waves["wf_blsub"]
        wfsg = waves["wf_savgol"]

        iwf = 2
        while True:
            if iwf != 2:
                inp = input()
                if inp == "q": exit()
                if inp == "p": iwf -= 2
                if inp.isdigit(): iwf = int(inp) - 1
            iwf += 1
            print(iwf)
            wf, ts = wfs[iwf], np.arange(wfs[iwf].shape[0])

            plt.cla()
            plt.plot(ts, wf, '-k', lw=2, alpha=0.5, label='raw wf')
            plt.plot(ts, wfsg[iwf], '-k', lw=1, label='savgol wf')
            plt.plot(ts, wflong[iwf], '-r', label='long: ' + wf1)
            plt.plot(ts, wfshort[iwf], '-b', label='short: ' + wf2)

            smax, simax = calcs[short + "_max"][iwf], calcs[short +
                                                            "_imax"][iwf]
            plt.plot(ts[simax], smax, ".k", ms=20, label="short trap max")

            # t0 and t_ftp
            plt.plot(
                ts[t0[iwf]], wfshort[iwf][t0[iwf]], '.g', ms=20, label="t0")
            plt.axvline(
                t_ftp[iwf], c='orange', lw=2, label="t_ftp: {}".format(ftp))

            # e_ftp
            plt.axhline(
                e_ftp[iwf], c='g', label="e_ftp: {:.2f}".format(e_ftp[iwf]))

            plt.xlabel("clock ticks", ha='right', x=1)
            plt.ylabel("ADC", ha='right', y=1)
            plt.legend(loc=2)
            plt.tight_layout()
            plt.show(block=False)
            plt.pause(0.001)


def num_peaks(waves, calcs, wfin="wf_maxc", test=False):
    """
    take the peakdet wf block and output:
    - the number of maxima
    - the sum of all the maxima
    """
    pks = waves[wfin]

    npeaks = np.count_nonzero(pks, axis=1)
    nsum = np.sum(pks, axis=1)

    calcs["n_curr_pks"] = npeaks
    calcs["s_curr_pks"] = nsum

    if test:
        wfs = waves["wf_notch"]
        wfc = waves["wf_current"]

        iwf = 2
        while True:
            if iwf != 2:
                inp = input()
                if inp == "q": exit()
                if inp == "p": iwf -= 2
                if inp.isdigit(): iwf = int(inp) - 1
            iwf += 1
            print(iwf)
            wf, ts = wfs[iwf], np.arange(wfs[iwf].shape[0])

            plt.cla()
            plt.plot(ts, wf / np.amax(wf), '-k', lw=2, alpha=0.5,
                     label='raw wf')
            plt.plot(ts, wfc[iwf] / np.amax(wfc[iwf]), '-b',
                     label='current wf, {} pks found'.format(npeaks[iwf]))

            ipk = np.where(pks[iwf] > 0)
            for pk in ipk[0]:
                plt.plot(ts[ipk], pks[iwf][ipk] / np.amax(wfc[iwf]), ".m", ms=20)

            plt.xlabel("clock ticks", ha='right', x=1)
            plt.ylabel('ADC', ha='right', y=1)
            plt.legend()
            plt.tight_layout()
            plt.show(block=False)
            plt.pause(0.01)


def overflow(waves, calcs, wfin="wf_blsub", nbit=14, test=False):
    """
    simple overflow checker.  asks if the max value is at the limit
    of the digitizer's range.  clint had to add a 0.45 factor to get the
    MJ60 wfs to be correctly tagged (ben used 0.5)
    """
    wfs = waves["wf_blsub"]
    maxes = np.amax(wfs, axis=1)
    ovr = maxes > 0.45 * 2**nbit
    calcs["overflow"] = ovr

    if test:
        iwf = 9
        while True:
            if iwf != 9:
                inp = input()
                if inp == "q": exit()
                if inp == "p": iwf -= 2
                if inp.isdigit(): iwf = int(inp) - 1
            iwf += 1
            print(iwf)
            wf, ts = wfs[iwf], np.arange(wfs[iwf].shape[0])

            plt.cla()
            plt.plot(
                ts, wf, '-k', label='raw wf.  overflow? {}'.format(ovr[iwf]))
            plt.xlabel("clock ticks", ha='right', x=1)
            plt.ylabel('ADC', ha='right', y=1)
            plt.legend(loc=4)
            plt.tight_layout()
            plt.show(block=False)
            plt.pause(0.01)


def tail_fit(waves, calcs, delta=1, wfin="wf_blsub", vec=True, test=False):
    """
    this is a "fast" wf fit, not a super duper accurate (slow) one.
    since curve_fit can't be vectorized, try np.polyfit.
    take the log of the wf tail, and fit to a polynomial.
    y(t) = log(A exp(-t/tau)) = log(A)  + (-1/tau) * t
                              = pfit[0] + pfit[1]  * t
    amp = np.exp(pfit[0])
    tau = -1 / pfit[1]
    """
    wfin = "wf_notch"
    vec = True
    tp_thresh = 0.8
    n_check = 3
    order = 1

    wfs = waves[wfin]
    ts = np.arange(wfs.shape[1])

    # add a delta to the 100 pct timepoint so we're sure we're on the tail
    nsamp = 1e10 / waves["settings"]["clk"] # Hz
    dt = int(nsamp * delta)
    tp100 = calcs["tp100"] + dt

    # fix out of range timepoints (these can mess up the vectorized polyfit)
    tp100[tp100 > tp_thresh * wfs.shape[1]] = 0

    # create a masked array to handle the different-length wf tails
    tails = np.full_like(wfs, np.nan)
    for i, tp in enumerate(tp100):
        tails[i, tp:] = wfs[i, tp:]
    tails = np.ma.masked_invalid(tails)
    block = np.ma.log(tails) # suppress neg value warnings

    t_start = time.time()
    if vec:
        """
        run the vectorized fit, which works great but is sensitive to timepoints
        being too near the end of the waveform -- it throws off the whole matrix.
        until we're sure this is fixed, check the fit results
        against `n_check` random single tail fits.
        """
        pfit = np.ma.polyfit(ts, block.T, order).T

        amps = np.exp(pfit[:,1])
        taus = -1 / pfit[:,0]
        calcs["tail_amp"] = amps
        calcs["tail_tau"] = taus

        # pol_fit = np.ma.polyfit(ts, block.T, 2).T
        # calcs["tail_p0"] = pol_fit[:,2]
        # calcs["tail_p1"] = pol_fit[:,1]
        # calcs["tail_p2"] = pol_fit[:,0]

        for iwf in np.random.choice(block.shape[0], n_check):
            check_fit = np.ma.polyfit(ts, block[iwf], order)
            ch_amp = np.exp(check_fit[1])
            ch_tau = -1 / check_fit[0]

            # if within 90%, they're fine. a polyfit mistake is OOM wrong
            pct1 = 100 * (ch_amp - amps[iwf]) / amps[iwf]
            pct2 = 100 * (ch_tau - taus[iwf]) / taus[iwf]
            if (pct1 > 90) | (pct2 > 90):
                print("WARNING: there are probably invalid tail values in this wf block.")
                print("iwf {}, check amp: {:.3e}  tau: {:.3e}".format(iwf, ch_amp, ch_tau))
                print("     original amp: {:.3e}  tau: {:.3e}".format(amps[iwf], taus[iwf]))
                print("     pct1: {:.2f}  pct2: {:.2f}".format(pct1, pct2))
    else:
        """
        run a non-vectorized fit with np.polyfit and np.apply_along_axis.
        for 200 wfs, this is about half as fast as the vectorized mode.
        """
        def poly1d(ts, wf, ord):
            return np.ma.polyfit(wf, ts, ord)

        pfit = np.apply_along_axis(poly1d, 1, block, ts, order)

        amps = np.exp(pfit[:,1])
        taus = -1 / pfit[:,0]
        calcs["tail_amp"] = amps
        calcs["tail_tau"] = taus

    print("Done.  Elapsed: {:.2e} sec.".format(time.time()-t_start))

    if test:
        wfbl = waves["wf_blsub"]
        iwf = 2
        while True:
            if iwf != 2:
                inp = input()
                if inp == "q": exit()
                if inp == "p": iwf -= 2
                if inp.isdigit(): iwf = int(inp) - 1
            iwf += 1
            print(iwf)
            plt.cla()
            plt.plot(ts, wfs[iwf], '-k', label=wfin)
            plt.plot(ts, wfbl[iwf], '-b', alpha=0.4, label="wf_blsub")

            # get the wf tail
            wf_tail = np.ma.filled(tails[iwf,:], fill_value = np.nan)
            idx = np.where(~np.isnan(wf_tail))
            wf_tail, ts_tail = wf_tail[idx], ts[idx]
            plt.plot(ts_tail, wf_tail, '-g', label='tail')

            # curve_fit, with exponential. (not easily vectorized)
            from scipy.optimize import curve_fit
            tmax = np.amax(wf_tail)
            def gaus(t, a, tau):
                return a * np.exp(-t/tau)
            pars, pcov = curve_fit(gaus, ts_tail, wf_tail,
                                   p0=(tmax,8000),
                                   bounds=[[0.8*tmax, 5000],[1.2*tmax, 20000]])
            perr = np.sqrt(np.diag(pcov))
            dc, dc_err = pars[1] / 100, perr[1] / 100
            plt.plot(ts_tail, gaus(ts_tail, *pars), '-m', lw=3,
                     label="curve_fit dc: {:.1f} +/- {:.3f}".format(dc, dc_err))

            # polyfit
            amp, tau = amps[iwf], taus[iwf]
            plt.plot(ts_tail, amp * np.exp(-ts_tail/tau), '-r',
                     label="polyfit dc: {:.1f}".format(tau/100))

            plt.xlabel("clock ticks", ha='right', x=1)
            plt.ylabel('ADC', ha='right', y=1)
            plt.legend(loc=4)
            plt.tight_layout()
            plt.show(block=False)
            plt.pause(0.01)

def cfd(waves, calcs, test=False):
    """
    huh, not really anything on cfd in scipy.
    i guess it's a special case of a more general filter.
    the algorithm on wikipedia seems pretty straightforward to implement.
    the signal is split into two parts.  one part is time-delayed, and the
    other is low pass filtered, and inverted. (you can probably permute these)
    https://en.wikipedia.org/wiki/Constant_fraction_discriminator\
    #/media/File:Operation_of_a_CFD.png
    """
    print("hi clint")


    # frac = 0.5 # Threshold for CFD trigger
    # thresh = 0.4 #
    # delay = 10e-9 # Delay for CFD differentiation
    # length = 10
    # ratio = 0.75

    # a, b = np.zeros(length), np.zeros(length)
    # b[0] = -1 * frac
    # b[length - 1] = 1.
    # a[0] = 1.
    # # FirFilter.__init__(self, b, a, 'constant fraction discriminator')
    # """
    # Apply generic FIR filter to *data* using scipy.signal.lfilter()
    # *data* 1D or 2D numpy array
    # # scipy.signal.lfilter(b, a, x, axis=-1, zi=None)
    # """
    # length = max(len(self.a),len(self.b))-1
    # if length > 0:
    #     if ( data.ndim == 1):
    #        initial = np.ones(length)
    #        initial *= data[0]
    #    elif ( data.ndim == 2):
    #        initial = np.ones( (data.shape[0], length) )
    #         for i in range(data.shape[0]):
    #             initial[i,:] *= data[i,0]
    #     else:
    #         print 'HELP.'
    #         pass
    #     filtered, zf = signal.lfilter(self.b, self.a, data, zi=initial)
    # else:
    #     filtered = signal.lfilter(self.b, self.a, data)
    # filtered = filtered.reshape(data.shape)
    # return filtered

    print('hi clint')


def fir():
    """
    FIR Filter, fir the win ;-)
    https://docs.scipy.org/doc/scipy-1.2.1/reference/generated/scipy.signal.firwin.html

    This might be better than computing a whole bunch of notch filters.
    Just do a study on the MJ60 power spectrum, and create a multiband filter

    FIR FAQ
    https://dspguru.com/dsp/faqs/fir/basics/
    """
    print("hi clint")
    numtaps = 3
    f = 0.1
    signal.firwin(numtaps, f)


def dcr(waves, calcs, test=False):
    """
    nick says the parameter should be called "dcr_og"
    """
    print("hi clint")


def gretina_overshoot(rc_us, pole_rel, freq=100E6):
    """
    for use with scipy.signal.lfilter
    """
    zmag = np.exp(-1. / freq / (rc_us * 1E-6))
    pmag = zmag - 10.**pole_rel

    num = [1, -zmag]
    den = [1, -pmag]

    return (num, den)


def curve_fit():
    """
    a curve_fit apply_along_axis function might be good, for special cases
    when we don't care about using more computation time
    """
    print("hi clint")

    # # curve_fit, with exponential. (not easily vectorized)
    # from scipy.optimize import curve_fit
    # tmax = np.amax(wf_tail)
    # def gaus(t, a, tau):
    #     return a * np.exp(-t/tau)
    # pars, pcov = curve_fit(gaus, ts_tail, wf_tail,
    #                        p0=(tmax,8000),
    #                        bounds=[[0.8*tmax, 5000],[1.2*tmax, 20000]])
    # perr = np.sqrt(np.diag(pcov))
    # dc, dc_err = pars[1] / 100, perr[1] / 100
    # plt.plot(ts_tail, gaus(ts_tail, *pars), '-m', lw=3,
    #          label="curve_fit dc: {:.1f} +/- {:.3f}".format(dc, dc_err))
