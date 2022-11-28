import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from dataclasses import dataclass

import funct
from scipy import signal, ndimage, interpolate


@dataclass
class Roi:
    X: list
    Z: list


class Profile:
    def __init__(self):
        self.c, self.q, self.m = 0, 0, 0  # line fit parameters

        self.gr = None  # first derivative
        self.roi = None  # ISO regions
        self.gs = None
        self.fig = None
        self.X = None
        self.Z = None
        self.Z0 = None

    # @funct.timer
    def openPrf(self, fname):
        z = []
        xs = 0
        zs = 0
        with open(fname, 'r') as fin:
            charlines = 0
            for line in fin.readlines():
                word = line.split()[0]
                if word == 'SPACING':  # linea di spacing x
                    xs = float(line.split()[2])
                    print(f'Spacing x: {xs}')
                if word == 'CZ':  # linea di spacing z
                    zs = float(line.split()[4]) * 10 ** 3
                    print(f'Scaling z: {zs}')

                try:  # salvo solo i valori numerici
                    z.append(float(word) * zs)
                except ValueError:
                    charlines += 1
            print(f'Skipped {charlines} word lines')
            z.pop(0)

            self.Z0 = self.Z = np.array(z)
            self.X = np.linspace(0, (len(z)) * xs, len(z))

    def setValues(self, X, Y):
        """
        Sets the values for the profile
        :param X: x values of profile
        :param Y: y values of profile
        """
        self.X = X
        self.Z0 = self.Z = Y

    def stepAuto(self):  # TODO: can you find a way to automate minD calculations?
        """
        Calculates the step height using the auto method
        :return: steps: array containing all found step heights on profile
        """

        def calcSteps():
            st = []
            definedPeaks = True
            for j in range(len(self.roi) - 2):  # consider j, j+1, j+2
                outerMeanL = np.mean(self.roi[j].Z)
                outerMeanR = np.mean(self.roi[j + 2].Z)
                innerMean = np.mean(self.roi[j + 1].Z)

                outerStdL = np.std(self.roi[j].Z)
                outerStdR = np.std(self.roi[j + 2].Z)
                innerStd = np.std(self.roi[j + 1].Z)

                step = innerMean - (outerMeanL + outerMeanR) / 2
                st.append(step)

                if outerStdL > abs(step) / 200 or outerStdR > abs(step) / 200 or innerStd > abs(step) / 200:
                    definedPeaks = False

            if not definedPeaks:
                print(funct.Bcol.WARNING + 'STEP HEIGHT MIGHT BE INCORRECT (PEAKS ARE POURLY DEFINED)' +
                      funct.Bcol.ENDC)

            return st, definedPeaks

        self.gr = np.gradient(self.Z)

        thresh = np.max(self.gr[30:-30]) / 1.5  # derivative threshold to detect peak, avoid border samples
        zero_cross = np.where(np.diff(np.sign(self.Z)))[0]
        spacing = (zero_cross[1] - zero_cross[0]) / 1.5

        peaks, _ = signal.find_peaks(self.gr, height=thresh, distance=spacing)
        valle, _ = signal.find_peaks(-self.gr, height=thresh, distance=spacing)

        self.roi = []  # regions of interest points
        p_v = np.sort(np.concatenate((peaks, valle)))  # every point of interest (INDEXES of x array)

        for i in range(len(p_v) - 1):
            locRange = round((p_v[i + 1] - p_v[i]) / 3)  # profile portion is 1/3 of region
            roi_start = p_v[i] + locRange
            roi_end = p_v[i + 1] - locRange
            self.roi.append(Roi(self.X[roi_start: roi_end],  # append to roi X and Y values of roi
                                self.Z[roi_start: roi_end]))
        steps, ok = calcSteps()
        return steps, ok

    def fitLineLS(self):
        """
        Least square line fit implementation
        """
        # create matrix and Z vector to use lstsq
        XZ = np.vstack([self.X.reshape(np.size(self.X)),
                        self.Z.reshape(np.size(self.Z))]).T
        (rows, cols) = XZ.shape
        G = np.ones((rows, 2))
        G[:, 0] = XZ[:, 0]  # X
        Z = XZ[:, 1]
        (m, q), resid, rank, s = np.linalg.lstsq(G, Z, rcond=None)  # calculate LS plane

        print(f'Params: m={m}, q={q}')

        self.m = m
        self.q = q
        self.c = -1  # y coefficient in line eq.

    def allignWithHist(self, start_m):
        tot_bins = int(np.size(self.X) / 25)
        threshold = 50 / tot_bins

        line_m = start_m  # start incline

        def calcNBUT():
            fig = plt.figure()
            ax = fig.add_subplot(211)
            bx = fig.add_subplot(212)

            hist, edges = self.histMethod(tot_bins)  # make the hist
            weights = hist / np.size(self.Z) * 100
            n_bins_under_threshold = np.size(np.where(weights < threshold)[0])  # how many bins under th

            ax.hist(edges[:-1], bins=edges, weights=weights, color='red')
            ax.axhline(y=threshold, color='b')
            bx.plot(self.X, self.Z)
            plt.show()

            return n_bins_under_threshold

        nbut = calcNBUT()

        # until I have enough bins < th keep loop
        while np.abs(line_m) > 0.005:  # nbut < (tot_bins - tot_bins / 20):
            self.Z = self.Z - self.X * line_m
            nbut_old = nbut
            nbut = calcNBUT()

            if nbut < nbut_old:  # invert rotation if we are going the wrong way
                line_m = -line_m / 2

    def histMethod(self, bins=100):
        """
        histogram method implementation
        :return: histogram values, bin edges values
        """
        hist, edges = np.histogram(self.Z, bins)
        return hist, edges

    def removeLine(self):
        z_line = (-self.X * self.m - self.q) * 1. / self.c
        self.Z = self.Z - z_line

    def __filterGauss(self, roi, cutoff, order=0):
        nsample_cutoff = cutoff / (np.max(self.X) / np.size(self.X))

        alpha = np.sqrt(np.log(2) / np.pi)
        sigma = nsample_cutoff * (alpha / np.sqrt(2 * np.pi))  # da norma ISO 16610-21  # * (1 - 0.68268949)
        print(f'Appliyng filter sigma: {sigma}')
        roi_filtered = ndimage.gaussian_filter1d(roi, sigma=sigma, order=order)

        return roi_filtered

    @funct.timer
    def roughnessParams(self, cutoff, ncutoffs, plot):  # TODO: check if this works
        """
        Applies the indicated filter and calculates the roughness parameters
        :param plot: shows roi plot
        :param cutoff: co length
        :param ncutoffs: number of cutoffs to considerate in the center of the profile
        :return: RA, RQ, RP, RV, RZ, RSK, RKU
        """

        # samples preparation for calculation of params
        def prepare_roi(pl=False):
            nsample_cutoff = cutoff / (np.max(self.X) / np.size(self.X))
            nsample_region = nsample_cutoff * ncutoffs

            border = round((np.size(self.Z) - nsample_region) / 2)
            roi_I = self.Z[border: -border]  # la roi sono i cutoff in mezzo

            envelope = self.__filterGauss(self.Z, cutoff)
            roi_F = roi_I - envelope[border: -border]  # applico il filtro per il calcolo

            if pl:
                fig, ax = plt.subplots()

                twin = ax.twinx()
                twin.set_ylabel('Filtered roi')

                ax.set_title(f'Gaussian filter: cutoffs: {ncutoffs}, cutoff length: {cutoff}')
                ax.plot(self.X, self.Z, alpha=0.2, label='Data')
                ax.plot(self.X[border: -border], roi_I, alpha=0.3, label='roi unfiltered')

                twin.set_ylim(np.min(roi_F) - 0.7 * (np.max(roi_F) - np.min(roi_F)),
                              np.max(roi_F) + 0.7 * (np.max(roi_F) - np.min(roi_F)))
                rF, = twin.plot(self.X[border: -border], roi_F, color='green', alpha=0.6, label='roi filtered')
                twin.tick_params(axis='y', colors=rF.get_color())

                ax.plot(self.X, envelope, color='red', label='filter envelope')

                ax.legend()
            return roi_F  # cutoff roi

        roi = prepare_roi(plot)

        RA = np.sum(abs(roi)) / np.size(roi)
        RQ = np.sqrt(np.sum(abs(roi ** 2)) / np.size(roi))
        RP = abs(np.max(roi))
        RV = abs(np.min(roi))
        RZ = RP + RV
        RSK = (np.sum(roi ** 3) / np.size(roi)) / (RQ ** 3)
        RKU = (np.sum(roi ** 4) / np.size(roi)) / (RQ ** 4)
        return RA, RQ, RP, RV, RZ, RSK, RKU

    #####################################################################################################
    #                                       PLOT SECTION                                                #
    #####################################################################################################
    def init_graphics(self):  # creates a figure subdivided in grid for subplots
        self.fig = plt.figure()
        self.gs = gridspec.GridSpec(3, 2)  # rows, cols

    def prfPlot(self, fname):  # plots the profile
        ax_prf = self.fig.add_subplot(self.gs[0, :])
        ax_prf.plot(self.X, self.Z, color='teal')
        funct.persFig(
            ax_prf,
            gridcol='grey',
            xlab='x [um]',
            ylab='z [nm]'
        )
        ax_prf.set_title('Profile ' + fname)

    def roiPlot(self):
        ax_roi = self.fig.add_subplot(self.gs[1, :])
        ax_roi.plot(self.X, self.Z, color='teal')
        ax_roi.plot(self.X, self.gr, color='blue')

        for roi in self.roi:
            ax_roi.plot(roi.X, roi.Z, color='red')  # hot, viridis, rainbow
            ax_roi.plot(self.X, self.gr, color='blue')

        funct.persFig(
            ax_roi,
            gridcol='grey',
            xlab='x [um]',
            ylab='z [nm]'
        )

    def linePlot(self):
        ax_lin = self.fig.add_subplot(self.gs[2, 0])
        ax_lin.plot(self.X, self.Z0, color='teal')

        z_line = (- self.m * self.X - self.q) * 1. / self.c
        ax_lin.plot(self.X, z_line, color='red')

        funct.persFig(
            ax_lin,
            gridcol='grey',
            xlab='x [um]',
            ylab='z [nm]'
        )

    def histPlot(self, hist, edges):
        ax_ht = self.fig.add_subplot(self.gs[2, 1])
        ax_ht.hist(edges[:-1], bins=edges, weights=hist / np.size(self.Z) * 100, color='red')
        funct.persFig(
            ax_ht,
            gridcol='grey',
            xlab='z [nm]',
            ylab='pixels %'
        )
