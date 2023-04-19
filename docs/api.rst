.. _swamp-api:

The SWAMP API
=============
The SWAMP API is the description of the methods that every SWAMP object needs to implement. This is done to ensure composability between objects.
Implementing these methods is **mandatory** for the object to be compatible with the other components of the swamp system.

There are two sets of methods that may be provided by a swamp object. It may provide both sets. The first set is the set of methods associated with an *endpoint*.
An endpoint is a node that accepts configuration from the User. It needs to provide the following methods:

Global API
----------
To allow for integration of swamp into either custom scripts or continuously operating services, the entire SWAMP is wrapped in a single API. This API handles dispatching
and scheduling global events and is the main point of contact for system integration aspects. The SWAMP library provides 4 methods to interface with the system.

:``grow``:
  This method is a factory method that generates the swamp object from a description. It allows the SWAMP to be instantiated easily on many different systems by
  scanning the hardware for the required recources before instantiating the SWAMP. The ``grow`` method has the following syntax:

  .. code-block:: python

   def grow(topology: dict[Any]) -> SWAMP:
       ...

  .. note::
    The integration of custom ICs will happen via integration into the SWAMP repository. Please reach out or submit a pull request if a new IC should be added.

:``configure``:
  The configure method is used to change the state of the Detector by passing it the desired state of the relevant config parameters. The global SWAMP object 
  will then dispatch the configuration to the relevant endpoints which validate the config before encoding then transmitting the configuration to the detector.
  This method blocks until the transaction is completed, meaning every change has been acknowleged by the hardware. If any error occures this method will raise
  it to be handeled by the control system. It has the following signature:

  .. code-block:: python

   def configure(config: 
       Union[list[dict[Any]], dict[Any]]) -> None:
       ...

  .. note::
    It is forseen that this function may allow for multiple threads to call it simultaneously. In the current iteration however, only a single call may be made and
    a lock is used to serialize access to the SWAMP API by multiple threads

:``read``:
  This method allows the control system to query the state of the detector. This may be one of two states.
  1. The state of the detector assuming all currently pending transactions are completed as expected, in which case the state is read from a cache kept by the SWAMP endpoints.
  2. The state of the actual hardware in which case the Software waits until all requests have been processed and then issues a hardware read for all requested parameters.
  The first read may be compleated fully asynchronously from any write currently being performed by the system.

  .. code-block:: python

   def read(config:
       Union[list[dict[Any]], dict[Any]]) \
       -> Union[dict[Any], None, list[dict[Any]]:
       ...


----

Endpoint API
------------


:``configure``: 
  This method allows users to pass in configuration that they want to set on the Device represented by the endpoint object. The user is responsible
  for sequencing the calls so that the target IC shows the desired behavior. The SWAMP API does not guarantee a specific sequence of parameter changes within
  one call of the configure method. It has the following signature:

  .. code-block:: python
           
   def configure(config: dict[Any]) -> None:
       ...
      
  The method should perfom the following steps:
  
  1. validate the configuration
  2. generate the message sequence to configure the object
  3. pass the generated messages to the transport

  .. note::
    Generating the messages is something that is IC specific and therefore needs to be done by an IC expert.
    SWAMP provides classes that handle the scheduling and communication with the other SWAMP objects, allowing the IC expert to focus on the chip specific
    behaviour of the swamp object. It is highly recommended that these classes are used in stead of rewriting them yourself. 
    For incorporating this object into your SWAMP class see the :ref:`synchronous memory` for more details.

:``receive_rsp``:
  This method allows the SWAMP system to return responses to the messages sent by an endpoint. This method should accept a list of messages
  and process them according to the specific needs of the SWAMP object.

  .. code-block:: python

   def receive_rsp(responses: list[SWAMPMessage]) -> None:
       ...

  The method needs to mutate the internal state of the object in response to incoming messages. There may be a difference between the packages sent to the transport
  and the memory operations performed by the :ref:`synchronous memory`. This will require some translation which should be straight forward in most cases.

  .. note::
    This should also be left for the :ref:`synchronous memory` to handle. This class will provide a synchronous interface to submit write and read requests,
    which then takes care of sequencing them accordingly.

----

Transport API
-------------
.. warning::
    TODO
