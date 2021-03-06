###################################################
## This is a part of Dymms 2.0
## Copyright Saswata Hier-Majumder, September 2017
## This program creates a sphere
## melt distribution 
## and solves for the velocity, pressure, and
## and compaction for Dirichlet BC
#################################################### 

######################################################################

from fenics import *
from mshr import*
import numpy, scipy, sys, math
#Add the path to Dymms module to the code
sys.path.insert(0, '../../modules/')
import core
import datetime
from dymms import *
#################import#####################################################


from scipy.interpolate import griddata
#################import#####################################################


parameters["form_compiler"]["cpp_optimize"] = True
parameters["form_compiler"]["optimize"] = True

# Test for PETSc or Epetra
if not has_linear_algebra_backend("PETSc") and not has_linear_algebra_backend("Epetra"):
    info("DOLFIN has not been configured with Trilinos or PETSc. Exiting.")
    exit()

if not has_krylov_solver_preconditioner("amg"):
    info("Sorry, this demo is only available when DOLFIN is compiled with AMG "
         "preconditioner, Hypre or ML.")
    exit()

if has_krylov_solver_method("minres"):
    krylov_method = "minres"
elif has_krylov_solver_method("tfqmr"):
    krylov_method = "tfqmr"
else:
    info("Default linear algebra backend was not compiled with MINRES or TFQMR "
         "Krylov subspace method. Terminating.")
    exit()

###########import###############################################################

param_file = sys.argv[1]
param   = core.parse_param_file(param_file)

# General parameters
logname  = param['logfile']
out_freq = param['out_freq']

#Set the problem domain
sphere=domain()

#Initial melt fraction field



# Set time stepping parameters
T = param['T']
dt = param['dt']
cfl = param['cfl']

#Set nondimensional paramters
sphere.da=param['da']
sphere.R=param['R']
sphere.B=param['B']
sphere.theta=param['theta']
sphere.dL=param['dL']
# Output files for quick visualisation
output_dir     = "output/"
extension      = "pvd"   # "xdmf" or "pvd"
initial_porosity_out = File(output_dir + "initial_porosity." + extension,\
                            "compressed")
velocity_out   = File(output_dir + "velocity." + extension, "compressed")
pressure_out   = File(output_dir + "pressure." + extension, "compressed")
porosity_out   = File(output_dir + "porosity." + extension, "compressed")
compact_out   = File(output_dir + "compaction." + extension, "compressed")
gam_out   = File(output_dir + "gamma." + extension, "compressed")

######################################################################
# Mesh and Paramters
######################################################################
s1 = Sphere(Point(0, 0, 0), 1.0)
mesh = generate_mesh(s1, 10)
######################################################################
# Function Spaces
######################################################################

# Define function spaces
# Velocity
V = VectorElement("Lagrange", mesh.ufl_cell(), 2)
# Pressure
Q = FiniteElement("Lagrange", mesh.ufl_cell(), 1)
#Compaction
OMEGA = FiniteElement("Lagrange", mesh.ufl_cell(), 1)
# Make a mixed space
W=dolfin.FunctionSpace(mesh, MixedElement([V,Q,OMEGA]))

# Output fuction space
# Porosity
X = FunctionSpace(mesh, "CG", 1)
# Velocity
Y = VectorFunctionSpace(mesh, "CG", 2)
# Pressure and porosity
Z = FunctionSpace(mesh, "CG", 1)

######################################################################
# Boundaries
######################################################################
class sphere_surface(SubDomain):
    def inside(self,x,on_boundary):
        r = sqrt(x[0]**2 + x[1]**2+x[2]**2)
        return on_boundary and near(r, 1.0,0.05)
surf=sphere_surface()


# Prescribe No-slip boundary condition for velocity
# on the sphere surface

noslip = Constant((0.0, 0.0, 0.0))
straining_flow=Expression(("0.05*x[0]","0.05*x[1]","-0.1*x[2]"),degree=2)
bcs = DirichletBC(W.sub(0),straining_flow, surf)

#analytical solution for benchmarking
uh=Function(Y)
uh.interpolate(straining_flow)

zero = Constant(0)


# ======================================================================
# Solution functions
# ======================================================================

# Split-field solution
U = Function(W)
u, p, c = U.split()

# Porosity at time t_n
phi0 = Function(X)
# Porosity at time t_n+1
phi1 = Function(X)

#Melting rate
gam=Function(X)
#Density 
# Spatial buoyancy
buyoancy=Function(X)
# ======================================================================
#  Develop the weak formulation
# ======================================================================
# Time step
dt = Expression("dt", dt=0.0,degree=1)
# Formulations
a_phi, L_phi,bb_phi = sphere.mass_conservation(X, phi0, u, dt, gam,mesh)
a_stokes, L_stokes, b = sphere.momentum_conservation(W, phi0, gam,buyoancy)
######################################################################
# Initial  condition and known functions
######################################################################
# Create an initial melt distribution
phi_init = Expression("0.01+0.001*x[0]*x[1]",degree=2)
phi0.interpolate(phi_init)
initial_porosity_out << phi0

#Function describing the rate of melting
# (-ve for freezing) as a function of space
gam_temp =Expression("0",degree=1)
gam.interpolate(gam_temp)
gam_out << gam
# Buoyancy

rho_temp=Expression("0.0",degree=1)
buyoancy.interpolate(rho_temp)
# Porosity
phi = Function(Z)
phi.interpolate(phi0)

t = 0.0
# Print log messages only from the root process in parallel
parameters["std_out_all_processes"] = False;
######################################################################
#  Initial velocity field
######################################################################
# Create Krylov solver and AMG preconditioner
solver = KrylovSolver(krylov_method, "amg")
solver.parameters["relative_tolerance"] = 0.000001
solver.parameters["maximum_iterations"] = 3000 #000
#solver.parameters["monitor_convergence"] = True

# Assemble system
A_stokes, b_stokes = assemble_system(a_stokes, L_stokes, bcs)

# Assemble preconditioner system
P, btmp = assemble_system(b, L_stokes, bcs)

# Associate operator (A) and preconditioner matrix (P)
solver.set_operators(A_stokes, P)

# Solve
solver.solve(U.vector(), b_stokes)

# Get sub-functions
u, p, c = U.split()
#Print error norm of velocity
l2=errornorm(u,uh,'L2')
print('l2 norm:',l2)
# ======================================================================
#  Time loop
# ======================================================================

# Set up time setp
dt.dt = 0.1;
# Solver matrices
A_phi, A_stokes = Matrix(), Matrix()

# Solver RHS
b_phi, b_stokes = Vector(), Vector()

# Create a ksp solver for porosity
solver_phi = KrylovSolver(krylov_method, "amg")
solver_phi.parameters["relative_tolerance"] = 0.000001
solver_phi.parameters["maximum_iterations"] = 3000 #000
solver_phi.parameters["monitor_convergence"] = True



# Create linear solver for Stokes-like problem
solver_U = KrylovSolver(krylov_method, "amg")
solver_U.parameters["relative_tolerance"] = 0.000001
solver_U.parameters["maximum_iterations"] = 200#000
#solver_U.parameters["monitor_convergence"] = True


tcount = 1
while (t < T):
    if t + dt.dt > T:
        dt.dt = T - t



    # Solve for U_n+1 and phi_n+1
    ########################################
    ##### Do this if an iterative solution for time
    ##### marching is desired
    # Compute U and phi1, and update phi0 <- phi1
    info("**** t = %g: Solve phi and U" % t)
    # Assemble system for porosity advection
    A_phi, b_phi = assemble_system(a_phi, L_phi)
    # Associate a preconditioner with the porosity advection
    P_phi, btmp_phi=assemble_system(bb_phi, L_phi)
    #Connect operator to equations
    solver_phi.set_operators(A_phi, P_phi)
    # Solve linear Stokes-type system
    solver_phi.solve(phi1.vector(), b_phi)
    #################################################
##### Do this if an iterative solver is not desired
# Solve linear porosity advection system

#solver_phi.solve(phi1.vector(), b_phi)
#solve(A_phi, phi1.vector(), b_phi, "minres", "default")
# solve(A_phi, phi1.vector(), b_phi)
################################################
# Update porosity
    phi0.assign(phi1)
    phi.interpolate(phi1)
    
    # Assemble Stokes-type system
    A_stokes, b_stokes = assemble_system(a_stokes, L_stokes, bcs)
    
    # Assemble preconditioner system
    P, btmp = assemble_system(b, L_stokes, bcs)
    
    # Associate operator (A) and preconditioner matrix (P)
    solver_U.set_operators(A_stokes, P)
    
    # Solve linear Stokes-type system
    solver_U.solve(U.vector(), b_stokes)
    
    
    if tcount % out_freq == 0:
        # Write data to files for quick visualisation
        # Velocity field
        u.rename("velocity", "")
        velocity_out  << u
        
        # Pressure field
        p.rename("pressure", "")
        pressure_out  << p
        
        # Compaction field
        c.rename("compaction", "")
        compact_out  << c
        
        # Porosity field
        phi.rename("porosity", "")
        porosity_out  << phi
        
        
        info("output results")
    
    info("**** New time step dt = %g\n" % dt.dt)
    t      += dt.dt
    tcount += 1
    info("**** New time t = %g\n" % t)




