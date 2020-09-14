import os
import numpy as np
import re
from pyxtal.lattice import Lattice
from ase import Atoms
from pyxtal.crystal import random_crystal
from pyxtal.interface.util import symmetrize_cell

class GULP():
    """
    This is a calculator to perform structure optimization in GULP
    At the moment, only inorganic crystal is considered
    Args:

    struc: structure object generated by Pyxtal
    ff: path of forcefield lib
    opt: 'conv', 'conp', 'single'
    """

    def __init__(self, struc, label="_", ff='reax', \
                 opt='conp', steps=1000, exe='gulp',\
                 input='gulp.in', output='gulp.log', dump='opt.cif'):
        if isinstance(struc, random_crystal):
            self.lattice = struc.lattice
            self.frac_coords, self.sites = struc._get_coords_and_species(absolute=False)
        elif isinstance(struc, Atoms):
            self.lattice = Lattice.from_matrix(struc.cell)
            self.frac_coords = struc.get_scaled_positions()
            self.sites = struc.get_chemical_symbols()

        self.structure = struc
        self.label = label
        self.ff = ff
        self.opt = opt
        self.exe = exe
        self.steps = steps
        self.input = self.label + input
        self.output = self.label + output
        self.dump = dump
        self.iter = 0
        self.energy = None
        self.stress = None
        self.forces = None
        self.positions = None
        self.optimized = False
        self.cputime = 0
        self.error = False


    def run(self):
        self.write()
        self.execute()
        self.read()
        self.clean()

    def execute(self):
        cmd = self.exe + '<' + self.input + '>' + self.output
        os.system(cmd)


    def clean(self):
        os.remove(self.input)
        os.remove(self.output)
        os.remove(self.dump)

    def to_ase(self):
        from ase import Atoms
        return Atoms(self.sites, scaled_positions=self.frac_coords, cell=self.lattice.matrix)

    def to_pymatgen(self):
        from pymatgen.core.structure import Structure
        return Structure(self.lattice.matrix, self.sites, self.frac_coords)

    def write(self):
        a, b, c, alpha, beta, gamma = self.lattice.get_para(degree=True)
        
        with open(self.input, 'w') as f:
            if self.opt == 'conv':
                f.write('opti {:s} conjugate nosymmetry\n'.format(self.opt))
            elif self.opt == "single":
                f.write('gradients noflag\n')
            else:
                f.write('opti stress {:s} conjugate nosymmetry\n'.format(self.opt))

            f.write('\ncell\n')
            f.write('{:12.6f}{:12.6f}{:12.6f}{:12.6f}{:12.6f}{:12.6f}\n'.format(\
                    a, b, c, alpha, beta, gamma))
            f.write('\nfractional\n')
            
            symbols = []
            for coord, site in zip(self.frac_coords, self.sites):
                f.write('{:4s} {:12.6f} {:12.6f} {:12.6f} core \n'.format(site, *coord))
            species = list(set(self.sites))

            f.write('\nSpecies\n')
            for specie in species:
                f.write('{:4s} core {:4s}\n'.format(specie, specie))

            f.write('\nlibrary {:s}\n'.format(self.ff))
            f.write('ewald 10.0\n')
            #f.write('switch rfo gnorm 1.0\n')
            #f.write('switch rfo cycle 0.03\n')
            if self.opt != "single":
                f.write('maxcycle {:d}\n'.format(self.steps))
            f.write('output cif {:s}\n'.format(self.dump))


    def read(self):
        with open(self.output, 'r') as f:
            lines = f.readlines()
        try: 
            for i, line in enumerate(lines):
                m = re.match(r'\s*Total lattice energy\s*=\s*(\S+)\s*eV', line)
                #print(line.find('Final asymmetric unit coord'), line)
                if m:
                    self.energy = float(m.group(1))

                elif line.find('Job Finished')!= -1:
                    self.optimized = True

                elif line.find('Total CPU time') != -1:
                    self.cputime = float(line.split()[-1])

                elif line.find('Final stress tensor components')!= -1:
                    stress = np.zeros([6])
                    for j in range(3):
                        var=lines[i+j+3].split()[1]
                        stress[j]=float(var)
                        var=lines[i+j+3].split()[3]
                        stress[j+3]=float(var)
                    self.stress = stress

                elif line.find(' Cycle: ') != -1:
                    self.iter = int(line.split()[1])

                elif line.find('Final fractional coordinates of atoms') != -1:
                    s = i + 5
                    positions = []
                    species = []
                    while True:
                        s = s + 1
                        if lines[s].find("------------") != -1:
                            break
                        xyz = lines[s].split()[3:6]
                        XYZ = [float(x) for x in xyz]
                        positions.append(XYZ)
                        species.append(lines[s].split()[1])
                    self.frac_coords = np.array(positions)

                elif line.find('Final Cartesian lattice vectors') != -1:
                    lattice_vectors = np.zeros((3,3))
                    s = i + 2
                    for j in range(s, s+3):
                        temp=lines[j].split()
                        for k in range(3):
                            lattice_vectors[j-s][k]=float(temp[k])
                    self.lattice = Lattice.from_matrix(lattice_vectors)
            if np.isnan(self.energy):
                self.error = True
                self.energy = 100000
                print("GULP calculation is wrong, reading------")
        except:
            self.error = True
            self.energy = 100000
            print("GULP calculation is wrong")

def single_optimize(struc, ff, mode=['C'], opt="conp", exe="gulp", symmetrize=True):
    if symmetrize:
        try:
            struc = symmetrize_cell(struc, mode)
        except:
            pass
    calc = GULP(struc, ff=ff, opt=opt)
    calc.run()
    if calc.error:
        print("GULP error in single optimize")
        return None, 100000, 0, True
    else:
        return calc.to_ase(), calc.energy, calc.cputime, calc.error

def optimize(struc, ff, modes=['C', 'C'], optimizations=["conp", "conp"], 
             exe="gulp", symmetrize=True):
    time_total = 0
    for mode, opt in zip(modes, optimizations):
        struc, energy, time, error = single_optimize(struc, ff, mode, opt, exe)
        time_total += time
        if error:
            return None, 100000, 0, True
    return struc, energy, time_total, False


if __name__ == "__main__":

    from pyxtal.crystal import random_crystal

    while True:
        count = 0
        struc = random_crystal(19, ["C"], [16], 1.0)
        if struc.valid:
            break
    struc, eng, time = optimize(struc.to_ase(), ff="tersoff.lib")
    print(struc)
    print(eng)
    print(time)
