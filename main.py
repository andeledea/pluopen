import numpy as np
import matplotlib.pyplot as plt
import os

import surface as sur
import profile as prf
import funct

import copy
import tkinter as tk
from tkinter import filedialog

import pandas as pd

# main
if __name__ == '__main__':
    # plt.style.use('dark_background')
    plt.rcParams["figure.autolayout"] = True
    plt.rcParams["figure.figsize"] = (12, 9)

    h = {}
    folder = 'C:/Elaborazione_profilometro/Symetrics/Txt_files'

    root = tk.Tk()
    root.withdraw()

    files = filedialog.askopenfilenames(parent=root, title='Choose files to process')
    df = pd.DataFrame(columns=['filename', 'h_hist', 'h_ISO (mean)', 'ok_ISO'])

    for fname in files:
        if os.path.isfile(fname):
            f = fname.removeprefix(folder)
            plu = sur.Surface()
            plu.openTxt(fname)

            plu.fitPlaneLS_bound(lambda a, b: a < b)
            plu.removePlane()

            hist, edges = plu.histMethod(bins=250)
            h_hist = funct.findHfromHist(hist, edges)

            extracted = copy.copy(plu.meanProfile('x'))
            h_iso, ok_steps = extracted.stepAuto()  # P_V are the peaks and valleys
            extracted.fitLineLS()

            df_tmp = pd.DataFrame({'filename': f,
                                   'h_hist': h_hist,
                                   'h_ISO (mean)': np.mean(np.abs(h_iso)),
                                   'ok_ISO': ok_steps},
                                  index=[0])
            df = pd.concat([df_tmp, df.loc[:]]).reset_index(drop=True)

            # plot section
            print('plotting results')
            plu.init_graphics()

            plu.pltPlot(f)
            plu.pltCplot()
            plu.planePlot()
            plu.histPlot(hist, edges)

            extracted.init_graphics()
            extracted.prfPlot(f)
            extracted.roiPlot()
            extracted.linePlot()

            plt.show()

    print('------- RESULTS -------')
    print(df)

    # with pd.ExcelWriter(folder + '/out.xlsx') as writer:
    #     df.to_excel(writer, sheet_name='Heights')
