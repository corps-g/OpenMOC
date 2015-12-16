import numpy as np
import matplotlib.pylab as pylab
import openmoc
import openmoc.compatible
import openmc.mgxs


###############################################################################
#                          Main Simulation Parameters
###############################################################################

options = openmoc.options.Options()

num_threads = options.getNumThreads()
spacing = options.getTrackSpacing()
num_azim = options.getNumAzimAngles()
tolerance = options.getTolerance()
max_iters = options.getMaxIterations()

openmoc.log.set_log_level('NORMAL')


###############################################################################
#                 Eigenvalue Calculation w/o SPH Factors
###############################################################################

# Initialize 2-group OpenMC multi-group cross section library for a pin cell
mgxs_lib = openmc.mgxs.Library.load_from_file(filename='mgxs', directory='.')

# Create an OpenMOC Geometry from the OpenCG Geometry
openmoc_geometry = \
    openmoc.compatible.get_openmoc_geometry(mgxs_lib.opencg_geometry)

# Load cross section data
openmoc_materials = \
    openmoc.materialize.load_openmc_mgxs_lib(mgxs_lib, openmoc_geometry)

# Initialize an OpenMOC TrackGenerator and Solver
openmoc_geometry.initializeFlatSourceRegions()
track_generator = openmoc.TrackGenerator(openmoc_geometry, num_azim, spacing)
track_generator.generateTracks()

# Initialize an OpenMOC Solver
solver = openmoc.CPUSolver(track_generator)
solver.setConvergenceThreshold(tolerance)
solver.setNumThreads(num_threads)

# Run an eigenvalue calulation with the MGXS from OpenMC
solver.computeEigenvalue()
solver.printTimerReport()
keff_no_sph = solver.getKeff()

# Extract the OpenMOC scalar fluxes
fluxes_no_sph = openmoc.process.get_scalar_fluxes(solver)


###############################################################################
#                Eigenvalue Calculation with SPH Factors
###############################################################################

# Compute SPH factors
sph, sph_mgxs_lib, sph_indices = \
    openmoc.materialize.compute_sph_factors(mgxs_lib, track_spacing=spacing,
                                            num_azim=num_azim,
                                            num_threads=num_threads)

# Load the SPH-corrected MGXS library data
materials = \
    openmoc.materialize.load_openmc_mgxs_lib(sph_mgxs_lib, openmoc_geometry)

# Run an eigenvalue calculation with the SPH-corrected modifed MGXS library
solver.computeEigenvalue()
solver.printTimerReport()
keff_with_sph = solver.getKeff()

# Report the OpenMC and OpenMOC eigenvalues
openmoc.log.py_printf('RESULT', 'OpenMOC keff w/o SPH: \t%1.5f', keff_no_sph)
openmoc.log.py_printf('RESULT', 'OpenMOC keff w/ SPH: \t%1.5f', keff_with_sph)
openmoc.log.py_printf('RESULT', 'OpenMC keff: \t\t:0.96261 +/- 0.00093')

# Extract the OpenMOC scalar fluxes
fluxes_sph = openmoc.process.get_scalar_fluxes(solver)


###############################################################################
#                       Plottting Scalar Fluxes
###############################################################################

openmoc.log.py_printf('NORMAL', 'Plotting data...')

# Allocate arrays for FSR-specific data to extract from OpenMOC model
num_fsrs = openmoc_geometry.getNumFSRs()
cell_ids = np.zeros(num_fsrs, dtype=np.int)
centroids = np.zeros(num_fsrs, dtype=np.float)
volumes = np.zeros(num_fsrs, dtype=np.float)

# Find the cell IDs, volumes, centroids and fluxes for each FSR
for fsr_id in range(num_fsrs):
    cell = openmoc_geometry.findCellContainingFSR(fsr_id)
    cell_ids[fsr_id] = cell.getId()
    volumes[fsr_id] = solver.getFSRVolume(fsr_id)
    centroids[fsr_id] = cell.getMinX()

# Organize cell IDs, volumes and fluxes in order of increasing centroid
indices = np.argsort(centroids)
centroids = centroids[indices]
cell_ids = cell_ids[indices]
volumes = volumes[indices]
fluxes_no_sph = fluxes_no_sph[indices,:]
fluxes_sph = fluxes_sph[indices,:]

# Get OpenMC fluxes
tot_fiss_src = 0.
openmc_fluxes = np.zeros((num_fsrs, mgxs_lib.num_groups))
for fsr_id, cell_id in enumerate(cell_ids):

    # Get NuFissionXS for cell from MGXS Library
    mgxs = mgxs_lib.get_mgxs(cell_id, 'nu-fission')

    # Store this cell's flux
    flux_tally = mgxs.tallies['flux']
    openmc_fluxes[fsr_id, :] = flux_tally.get_values().flatten()

    # Increment the total fission source
    nu_fission = mgxs.tallies['nu-fission']
    tot_fiss_src += np.sum(nu_fission.mean)

# Normalize OpenMC flux to total fission source * volume to compare to OpenMOC
openmc_fluxes /= volumes[:,np.newaxis] * tot_fiss_src

# Plot the OpenMOC and OpenMC spatially-varying fluxes
for group in range(mgxs_lib.num_groups):
    fig = pylab.figure()
    pylab.plot(centroids, openmc_fluxes[:,group])
    pylab.plot(centroids, fluxes_no_sph[:,group])
    pylab.plot(centroids, fluxes_sph[:,group])
    pylab.legend(['openmc', 'openmoc (w/o sph)', 'openmoc (sph)'],loc='best')
    pylab.title('Volume-Averaged Scalar Flux (Group {})'.format(group+1))
    pylab.xlabel('x [cm]')
    pylab.ylabel('flux')
    pylab.savefig('flux-group-{}.png'.format(group+1), bbox_inches='tight')
