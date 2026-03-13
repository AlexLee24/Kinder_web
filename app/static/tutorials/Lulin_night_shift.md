# Lulin night shift duty:

## Trigger

1. **Lulin weather:** 
    - https://www.lulin.ncu.edu.tw/weather/
    - https://www.meteoblue.com/en/weather/week/lulin-qianshan_taiwan_6725044

2. **Check GCN Circular, AstroNote, ATel:**
    - https://gcn.nasa.gov/circulars
    - https://www.wis-tns.org/astronotes
    - https://astronomerstelegram.org/

3. **For internal people who has access to PESSTO marshall:** 
    - Check new ATLAS < 100 Mpc objects (also can check slack channel - "daily-report")
    - https://star.pst.qub.ac.uk/sne/atlas4/userlist_quickview/44/

4. **Send a trigger to Lulin SLT, and LOT Filler time:**
    - For detail to check [Trigger_app_readme](Trigger_app_readme.md) and [Trigger_app_usage](Trigger_app_usage.md)

5. **If there is new EP trigger at control-room, wake up Janet, Amar, Sheng.**

---

## After Observe

- reduce data
- measure photometry
- write report

---

## Templates and Resources

### 1. Where to find a template? (or use autophot auto download templates):
- **DESI LS:** https://www.legacysurvey.org/viewer?ra=103.7785&dec=-39.3393&zoom=15&mark=1167.5112917,12.242#213.96%20-21.596
- **Download cutout:** https://www.legacysurvey.org/viewer/cutout.fits?ra=178.7560&dec=-20.9819&layer=ls-dr10&pixscale=0.1&bands=r&size=3000
- **Pan-STARRS1:** http://ps1images.stsci.edu/cgi-bin/ps1cutouts
- **SDSS:** https://skyserver.sdss.org/dr16/en/tools/chart/navi.aspx
- **Skymapper:** https://skymapper.anu.edu.au/image-cutout/requests/H03FYYYC/

### 2. Lulin EP GCN template:
- optical counterpart discovery
- follow up observations for the counterpart
- detection limit

> To make a draft and for multi people to edit: https://pads.ccc.de

#### (1) Latest template:

```text
EP251118a: Optical detection with Kinder observations

Y.-H. Lee, A. Aryan, C.-S. Lin (all NCU), A. K. H. Kong (NTHU), T.-W. Chen (NCU), J. Gillanders, S. J. Smartt (both Oxford), Y. J. Yang (NYUAD), A. Sankar.K, Y.-C. Pan, C.-C. Ngeow, M.-H. Lee, C.-H. Lai, W.-J. Hou, H.-C. Lin, H.-Y. Hsiao, J.-K. Guo (all NCU), S. Yang, Z. N. Wang, L. L. Fan, G. H. Sun (all HNAS), H.-W. Lin (UMich), H. F. Stevance, S. Srivastav, L. Rhodes (all Oxford), M. Nicholl, M. Fulton, T. Moore, K. W. Smith, C. Angus, A. Aamer (all QUB), A. Schultz and M. Huber (both IfA, Hawaii) report: 

We observed the field of the fast X-ray transient EP251118a (Jiang et al., GCN 42749) using the 1m LOT at Lulin Observatory in Taiwan as part of the Kinder collaboration (Chen & Yang et al., 2025, ApJ, 983, 86, doi:10.3847/1538-4357/adb428). The first LOT epoch of observations started at 16:21 UTC on the 19th of November  2025 (MJD 60998.681), 23.64 hr after the EP-WXT trigger. 

We utilized the astroalign (Beroiz et al. 2020, A&C, 32, 100384) and astropy (Astropy Collaboration et al. 2022, ApJ, 935, 167) packages to align and stack the individual frames. We utilized the Python-based package AutoPhOT (Brennan & Fraser, 2022, A&A, 667, A62) to perform template subtraction with the DESI Legacy Survey (Dey et al. 2019, AJ 157, 168) DR10 image using the 'hotpants' (Becker A., 2015, ascl.soft. ascl:1504.004) algorithm. In the difference image, we clearly detected the optical counterpart candidate proposed by Malesani et al. (GCN 42751) at a spectroscopic redshift of z = 1.216 (An et al., GCN 42756), and confirmed by Belkin et al. (GCN 42758); Yadav et al. (GCN 42760); Busmann et al. (GCN 42763); Francile et al. (GCN 42767); and Urquijo-Rodríguez et al. (GCN 42773). 

Moreover, we further utilized AutoPhOT to perform the PSF photometry. The details of the observations and the measured magnitude(in the AB system) are as follows:

Telescope | Filter | MJD (start) | t-t0 (hr) | Exposure (s) | Magnitude | avg. Seeing | med. Airmass
LOT | r | 60998.681 | 23.64 | 300  * 6 | 21.136 +/- 0.049 | 1".47 | 1.67

The presented magnitude is calibrated using the field stars from the ATLAS-RefCat2 catalog from MAST (Tonry J. L. et al. 2018, ApJ, 867, 105) and is not corrected for the expected Galactic foreground extinction of A_r = 0.034 mag in the direction of the transient (Schlafly & Finkbeiner 2011). The methodology, details on the Lulin observatory telescopes, and a compilation of our optical follow-up campaign for FXTs discovered within the first year of operation of the Einstein-Probe mission can be found in Aryan et al. 2025, ApJS, 281, 20, doi:10.3847/1538-4365/adfc69.
```

#### (2) EPXXXXXXa: Kinder optical counterpart candidate

```text
(XXX night-shift person), Y.-H. Lee, A. Aryan, T.-W. Chen, Y. J. Yang, W.-J. Hou, H.-Y. Hsiao (all NCU), A. K. H. Kong (NTHU), J. Gillanders (Oxford), S. J. Smartt (Oxford/QUB), M.-H. Lee, Y.-C. Pan, C.-C. Ngeow, A. Sankar. K, C.-H. Lai, C.-S. Lin, H.-C. Lin, J.-K. Guo (all NCU), S. Yang, L. L. Fan, Z. N. Wang, G. H. Sun (all HNAS), H.-W. Lin (UMich), H. F. Stevance, S. Srivastav, L. Rhodes (all Oxford), M. Nicholl, M. Fulton, T. Moore, K. W. Smith, C. Angus, A. Aamer (all QUB), A. Schultz and M. Huber (both IfA, Hawaii) report:

We observed the field of the fast X-ray transient EPXXXXXXa (XXX et al., GCN XXXXX) using the 40cm SLT telescope/Lulin One-meter Telescope (LOT) at Lulin Observatory in Taiwan as part of the Kinder collaboration (Chen & Yang et al., 2025, ApJ, 983, 86). The first SLT/LOT epoch of observations started at XX:XX UT on XXth(date) of XXX(month) 2024 (MJD = 60XXX.XXX), X.XX days after the EP trigger. We used the Kinder pipeline (Yang et al. 2021, A&A 646, 22) to stack the images and subtract the stacked images with the DESI Legacy Survey/Pan-STARRS1/SDSS template images. 

We detected an optical transient in the difference image, at RA = XX:XX:XX.XXX, Dec = -XX:XX:XX.XX (which is XX.X arcsec away from the reported coordinate of EPXXXXXXa by XXX et al., GCN XXXXX). 

The details of the observations and measured PSF magnitudes (in the AB system) of the possible counterpart of EPXXXXXXa are as follows: 

Telescope | Filter | MJD | t-t0 | Exposure | Magnitude | avg. Seeing | med. Airmass
LOT | r | 60XXX.XXX | X.XX hrs | 300 sec * X | XX.XX +/- 0.XX | X".X | X.XX 

The presented magnitudes are calibrated using the field stars from the Pan-STARRS1 catalog and are not corrected for the expected Galactic foreground extinction corresponding to a reddening of E_(B-V) = 0.241 mag in the direction of the burst (Schlafly & Finkbeiner 2011).

Further follow-up observations are encouraged to identify the nature of this X-ray transient. 

'SFFT' (Hu, L., Wang, L., Chen, X., & Yang, J. 2022, ApJ, 936, 157)
```

#### (3) EP24xxxxa: Optical upper limit with Kinder observations  

```text
We observed the field of the fast X-ray transient EP24xxxxa (xxxxx et al., GCN xxxxx, GCN) using the 1m LOT / 40cm SLT at the Lulin Observatory in Taiwan as part of the Kinder collaboration (Chen & Yang et al., 2025, ApJ, 983, 86). The first SLT epoch of observations started at xx:xx UTC on Xth Month 2024 (MJD 60xxx.xxx), xx.xx hrs after the EP-WXT trigger.   

We utilize the astroalign (Beroiz et al., 2020, A&C, 32, 100384) and astropy (Astropy Collaboration et al., 2022, ApJ, 935, 167) packages to align and stack the individual frames. We do not find any new source in the stacked frame within the xx.x arcminutes/arcseconds error circle of EP-WXT/EP-FXT  in comparison to the Pan-STARRS1 3Pi archive images (Chambers et al. 2016 arXiv:1612.05560).

Finally, we utilized the Python-based package AutoPhOT (Brennan & Fraser, 2022, A&A, 667, A62) to perform aperture photometry on our stacked frames. The details of the observations and measured 3-sigma upper limit (in the AB system) are as follows:  

--------------------------------------------------------------------------------------------------------------------------- 
Telescope | Filter | MJD (start) | t-t0 (hr) | Exposure (s) | Magnitude | avg. Seeing | med. Airmass   
SLT/LOT | r | 60xxx.xx | xx.xx | 300 * N | > xx.x | x".xx | x.xx   

The presented magnitude was calibrated using the field stars from the Pan-STARRS1/SDSS/APASS/SKYMAPPER catalog and was not corrected for the expected Galactic foreground extinction corresponding to a reddening of A_r = x.xx mag in the direction of the transient (Schlafly & Finkbeiner 2011).  
```

#### (4) EPXXXXXXa: Optical upper limit with Kinder observations

```text
We observed the field of the fast X-ray transient EPXXXXXXa (XXX et al., GCN XXXXX) using the 40cm SLT at Lulin Observatory in Taiwan as part of the Kinder collaboration (Chen & Yang et al., 2025, ApJ, 983, 86). The first SLT epoch of observations started at XX:XX UT on XXth(date) of XXX(month) 2024 (MJD = 60XXX.XXX), X.XX days after the EP trigger. We used the Kinder pipeline (Yang et al. 2021, A&A 646, 22) to stack the images and subtract the stacked images with the DESI Legacy Survey DR10 template images. 

We do not detect any optical counterpart in the errorbox of X arcminute around the position of the EP source specified by XXX et al., (GCN XXXXX). The details of the observations and the corresponding 2.5 sigma upper limit (in the AB system) in our combined image are as follows:

Telescope | Filter | MJD (start) | t-t0 | Exposure | Magnitude | avg. Seeing | med. Airmass
SLT | r | 60XXX.XXX | X.XX days | 300 sec * XX | > XX.XX | X".X | X.XX

The reported upper limit is calibrated against nearby stars from SDSS and is not corrected for the expected Galactic foreground extinction corresponding to a reddening of E_(B-V) = X.XX mag in the direction of the EP source (Schlafly & Finkbeiner 2011).
```

#### (5) Most recent GCN:

```text
GCN Circular 38061
Subject: EP241101a: Optical upper limits with Kinder observations
Date: 2024-11-03T15:29:37Z (17 hours ago)
From: Amar Aryan at National Central University, Institute of Astronomy (NCUIA) <amararyan941@gmail.com>
Via: Web form

A. Aryan, T.-W. Chen, W.-J. Hou (all NCU), A. K. H. Kong (NTHU), J. Gillanders (Oxford), S. J. Smartt (Oxford/QUB), Y.-H. Lee, Y. J. Yang, A. Sankar. K, Y.-C. Pan, C.-C. Ngeow, M.-H. Lee, H.-C. Lin, C.-H. Lai, H.-Y. Hsiao, C.-S. Lin, J.-K. Guo (all NCU), S. Yang, Z. N. Wang, L. L. Fan, G. H. Sun (all HNAS), H.-W. Lin (UMich), H. F. Stevance, S. Srivastav, L. Rhodes (all Oxford), M. Nicholl, M. Fulton, T. Moore, K. W. Smith, C. Angus, A. Aamer (all QUB), A. Schultz and M. Huber (both IfA, Hawaii) report: 

We observed the field of the fast X-ray transient EP241101a (Liang et al., GCN 38039; Perez-Garcia et al., GCN 38047; Lipunov et al., GCN 38049; Adami et al., GCN 38060) using the 1m LOT at Lulin Observatory in Taiwan as part of the Kinder collaboration (Chen & Yang et al., 2025, ApJ, 983, 86). The first LOT epoch of observations started at 16:59 UTC on the 2nd of November 2024 (MJD = 60616.707), 0.71d after the EP WXT trigger. 

We utilized the astroalign (Beroiz et al. 2020, A&C, 32, 100384) and astropy (Astropy Collaboration et al. 2022, ApJ, 935, 167) packages to align and stack the individual frames. We do not find any evidence of a new and uncataloged source in the stacked images within the 2.8 arcminute error circle of EP-WXT localization. 

Moreover, we utilized the Python-based package AutoPhOT (Brennan & Fraser, 2022, A&A, 667, A62) to perform the PSF photometry on our stacked frames. The details of the observations and measured 3-sigma upper limits  (in the AB system) are as follows:

Telescope | Filter | MJD (start) | t-t0 (d) | Exposure (s) | Magnitude | avg. Seeing | med. Airmass
LOT | r | 60616.707 | 0.71  | 300  * 6 | >22.9| 1".47 | 1.08
LOT | g | 60616.730 | 0.73  | 300 * 6 | >23.0| 1".39 | 1.16

The presented magnitudes are calibrated using the field stars from the SDSS catalog and are not corrected for the expected Galactic foreground extinction corresponding to a reddening of E(B-V) = 0.17 mag in the direction of the transient (Schlafly & Finkbeiner 2011).
```


