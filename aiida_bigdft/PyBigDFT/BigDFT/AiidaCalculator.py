from Calculators import SystemCalculator, Runner
from futile.Utils import write as safe_print
from futile.Utils import dict_merge
import InputActions
import Inputfiles

import six
import os

import aiida
#from aiida import orm
from aiida.common import datastructures, exceptions
from aiida.engine import launch, CalcJob
from aiida.parsers import Parser
from aiida.orm.nodes.data import List, SinglefileData
from aiida.plugins import DataFactory
from aiida.orm import load_code, load_node
from aiida.engine import Process

class BigDFTCalcJob(CalcJob):
    """Simple `CalcJob` implementation"""

    @classmethod
    def define(cls, spec):
        super(BigDFTCalcJob, cls).define(spec)
        spec.input('metadata.options.command_line', valid_type=six.string_types, default='')
        spec.input('metadata.options.local_copy_list', valid_type=List)
        spec.input('metadata.options.retrieve_list', valid_type=List)
#        spec.input('metadata.options.output_filename', valid_type=six.string_types, default="log.yaml")
        
    def prepare_for_submission(self, folder):
        codeinfo = datastructures.CodeInfo()
        codeinfo.code_uuid = self.inputs.code.uuid
#        codeinfo.stdout_name = outfile
        codeinfo.withmpi = self.inputs.metadata.options.withmpi
        if self.inputs.metadata.options.command_line is not '':
          codeinfo.cmdline_params = self.inputs.metadata.options.command_line.split()
#        print(self.local_options['command_line'])
        #local_copy_list = []
        # Prepare a `CalcInfo` to be returned to the engine
        calcinfo = datastructures.CalcInfo()
        calcinfo.codes_info = [codeinfo]
        calcinfo.local_copy_list = self.inputs.metadata.options.local_copy_list.get_list()
        calcinfo.retrieve_list = self.inputs.metadata.options.retrieve_list.get_list()
#        self.options['scheduler_stdout']="job.stdout"
        return calcinfo

#class BigDFTParser(Parser):
#    def __init__(self, node):
#    def parse():

                
class AiidaCalculator(SystemCalculator):
    """Run of an aiida process.
    """

    def __init__(self,
                 omp=os.environ.get('OMP_NUM_THREADS', '1'),
                 mpi_run=os.environ.get('BIGDFT_MPIRUN', ''),
                 dry_run=False, skip=False, code="bigdft@localhost", verbose=True, **kwargs):
        Runner.__init__(self,omp=str(omp), mpi_run=mpi_run,
                        dry_run=dry_run, skip=skip, verbose=verbose, **kwargs )
        # Build the command setting the number of omp threads
        self.code=load_code(code)
        self.job=BigDFTCalcJob
        self.command="" #we don't want the executable and such
        self.run_dir="."#ignore this for datasets, as aiida splits each computation in its own folder
        self.logfiles={}#store logfiles and names in order to skip execution if necessary.
        self.outputs={}#store output information on all runs.
        safe_print('Initialize an Aiida Calculator for %s with %d machine(s), %d processes per machine, and %s cores per process' % ((self.code),self._global_options.get('num_machines', 1),self._global_options.get('mpiprocs_per_machine', 1),self._global_options['omp'])  )
        #% str(self.run_options.get('num_machines', 1)) % 'machines, '  % str(self.run_options.get('mpiprocs_per_machine', 1)) % 'processes per machine, and ' % str(self.run_options['omp']) % 'cores per proc')

    def _ensure_run_directory(self):
        pass
        
    def pre_processing(self):
        """
        Generate files for run
        """
        self.metadata={
        'label' : self.run_options.get('name', ''),
        'description' : "AiiDA calc" + self.run_options.get('name', ''),
        'options' : {
            'resources' : {
                'num_machines': self.run_options.get('num_machines', 1), 
                'num_mpiprocs_per_machine': self.run_options.get('mpiprocs_per_machine', 1),
                'num_cores_per_mpiproc': self.run_options.get('omp', 1)
                },
            'withmpi' : True,
            'environment_variables': {"OMP_NUM_THREADS": str(self.run_options.get('omp', 1)) },
            'max_wallclock_seconds' : self.run_options.get('walltime', 30 * 60),
            'scheduler_stdout':'_scheduler-stdout.txt',
            'scheduler_stderr':'_scheduler-stderr.txt'
            }
        }
        if 'queue_name' in self.run_options:
            self.metadata['options']['queue_name']=self.run_options['queue_name']
        if 'account' in self.run_options:
            self.metadata['options']['account']=self.run_options['account']
        if 'mem' in self.run_options:
            self.metadata['options']['max_memory_kb']=self.run_options['mem']
#        print(self.metadata)
        run_args=SystemCalculator.pre_processing(self)

        #input files needed for calculation. This is basically prepare_for_submission
        input_filedata = SinglefileData(file=os.path.abspath(self._get_inputfilename())).store()

        local_copy_list=[(input_filedata.uuid, input_filedata.filename,input_filedata.filename)]
        #setup pseudopotentials if needed
        for filename in self._get_inputpseudos():
            pseudo_filedata = SinglefileData(file=os.path.abspath(filename)).store()
            local_copy_list.append((pseudo_filedata.uuid, pseudo_filedata.filename,filename))
        posinp_filename = self.run_options['input'].get('posinp', None)
        if posinp_filename is None:
            posinp_filename = self.run_options.get('posinp', None)
        if posinp_filename is not None:
            print(posinp_filename)
            posinp_filedata = SinglefileData(file=os.path.abspath(posinp_filename)).store()
            local_copy_list.append((posinp_filedata.uuid, posinp_filedata.filename,posinp_filename))
        name=self.run_options.get('name', 'log.yaml')
        outfile=name
        timefile="time.yaml"
        if name is not 'log.yaml':
            outfile = "log-"+name+".yaml"
            timefile = "time-"+name+".yaml"
#        self.job.local_options={
        retrieve_list=List()
        retrieve_list.extend([outfile, timefile, "forces*","final*", ["./debug/bigdft-err*",".",2]])
        retrieve_list.store()
        self.metadata['options']['retrieve_list']= retrieve_list
        local_copy_List=List()
        local_copy_List.extend(local_copy_list)
        local_copy_List.store()
        self.metadata['options']['local_copy_list']= local_copy_List
        self.metadata['options']['command_line']= self._get_command()
#        }
        return run_args

    def process_run(self, **kwargs):
        """Finally launch the code.
        Routine associated to the running of the ``bigdft`` executable.
        """
        # check if the debug file will be updated (case of erroneous run)
        timedbg = self._get_debugfile_date()
        # Run the command
        out = launch.run(self.job,code=self.code,metadata=self.metadata)
        name = self.run_options.get('name', '')
        self.outputs[name]=out
        logname = out['retrieved']._repository._get_base_folder().get_abs_path(self._get_logname())
        return {'timedbg': timedbg, 'logname': logname}
        
    def run(self, **kwargs):
        self._run_options(**kwargs)
        name = self.run_options.get('name', '')
        async = self.run_options.get('async', False)
        if self.run_options['skip'] and name in self.logfiles:
            return self.logfiles[name]
        else:
            run_args=self.pre_processing()
            if(async):
              node = launch.submit(self.job,code=self.code,metadata=self.metadata)
              run_results={'node': node}
              dict_merge(dest=run_args, src=run_results)
              return run_args
            else:
              run_results = self.process_run(**run_args)
    #          safe_print('run_args',run_args,'run_results',run_results)
              dict_merge(dest=run_args, src=run_results)
    #          safe_print('run_updated, again',run_args)
              self.logfiles[name] = SystemCalculator.post_processing(self,**run_args)
              print("setting data dir to "+self.outputs[name]['retrieved']._repository._get_base_folder().abspath)
              setattr(self.logfiles[name],"data_directory",self.outputs[name]['retrieved']._repository._get_base_folder().abspath)
              return self.logfiles[name]

    def submit(self, **kwargs):
        self._run_options(**kwargs)
        name = self.run_options.get('name', '')
        if self.run_options['skip'] and name in self.logfiles:
            return self.logfiles[name]
        else:
            run_args=self.pre_processing()
            node = launch.submit(self.job,code=self.code,metadata=self.metadata)
            run_results={'node': node}
            dict_merge(dest=run_args, src=run_results)
            return run_args

    def get_logs(self, pk, name):
#      name = self.run_options.get('name', '')
      self.outputs[name]=load_node(pk).outputs
      logname = 'log-' + name + '.yaml' if name else 'log.yaml'
      logfile = self.outputs[name]['retrieved']._repository._get_base_folder().get_abs_path(logname)
      self.run_options['name'] = name #to avoid comparing times with wrong input name
      timedbg = self._get_debugfile_date()
      command = self._get_command()
      run_args={'timedbg': timedbg, 'logname': logfile, 'command': command}
      self.logfiles[name] = SystemCalculator.post_processing(self,**run_args)
      print("setting data dir to "+self.outputs[name]['retrieved']._repository._get_base_folder().abspath)
      setattr(self.logfiles[name],"data_directory",self.outputs[name]['retrieved']._repository._get_base_folder().abspath)
      return self.logfiles[name]
            
    def _get_inputpseudos(self):
        return {}

